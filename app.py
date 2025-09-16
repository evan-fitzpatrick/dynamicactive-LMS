from pathlib import Path
import json
import re
import markdown2
import requests # <-- Added
import os # <-- Added
import sys # <-- Added
from flask import Flask, render_template, url_for, request, jsonify, abort, redirect

app = Flask(__name__)

# --- Corrected File Paths ---
DATA_PATH = Path(__file__).parent / "data"
LESSONS_PATH = DATA_PATH / "lessons"  # This now correctly points to the directory

# --- Helper and Parsing Functions ---

def load_data():
    """Loads static data like brand and user info."""
    with open(DATA_PATH / "seed.json", "r", encoding="utf-8") as f:
        return json.load(f)

def slugify(title):
    """Converts a string to a URL-friendly slug."""
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

def parse_lesson_file(slug):
    """Gets lesson data from its specific JSON file and returns HTML content."""
    lesson_file = LESSONS_PATH / f"{slug}.json"
    if not lesson_file.exists():
        return None, None, None

    with open(lesson_file, "r", encoding="utf-8") as f:
        lesson = json.load(f)

    title = lesson.get("title", "Lesson")
    markdown_content = lesson.get("markdown_content", "")
    answer_key = lesson.get("answer_key", {})

    # Remove the H3 title from the markdown before rendering to HTML
    title_match = re.search(r'###\s*(.*)', markdown_content)
    if title_match:
        content_for_html = markdown_content[title_match.end():].strip()
    else:
        content_for_html = markdown_content
    
    html_content = markdown2.markdown(content_for_html)

    return title, html_content, answer_key

def parse_raw_lesson_file(slug):
    """Gets raw lesson data from its specific JSON file for the edit page."""
    lesson_file = LESSONS_PATH / f"{slug}.json"
    if not lesson_file.exists():
        return None, None, None

    with open(lesson_file, "r", encoding="utf-8") as f:
        lesson = json.load(f)

    title = lesson.get("title", "Lesson")
    markdown_content = lesson.get("markdown_content", "")
    answer_key = lesson.get("answer_key", {})
    # Pretty-print the JSON for the textarea
    json_string = json.dumps(answer_key, indent=2)

    return title, markdown_content, json_string

def generate_ai_summary(system_prompt, user_prompt, fallback_summary="Here is your summary for the day."):
    """Generates a summary using an AI model from Openrouter."""
    print('Making summary request to Openrouter')
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        try:
            with open('openrouter_key.txt', 'r') as keyfile:
                api_key = keyfile.read().strip()
        except FileNotFoundError:
            print("AI summary generation skipped: API key file not found.", file=sys.stderr)
            return fallback_summary

    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            data=json.dumps({
                "model": "openai/gpt-3.5-turbo",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": 100,
                "temperature": 0.7,
            }),
            timeout=15
        )
        response.raise_for_status()
        ai_response = response.json()
        summary = ai_response['choices'][0]['message']['content'].strip()
        print(f'Got response! {summary}')
        # Clean up potential quotation marks from the response
        if summary.startswith('"') and summary.endswith('"'):
            summary = summary[1:-1]
        return summary
    except requests.exceptions.RequestException as e:
        print(f"AI summary API request failed: {e}", file=sys.stderr)
        return fallback_summary
    except (KeyError, IndexError) as e:
        print(f"Failed to parse AI summary response: {e}", file=sys.stderr)
        return fallback_summary
    except Exception as e:
        print(f"An unexpected error occurred during AI summary generation: {e}", file=sys.stderr)
        return fallback_summary

def grade_with_llm(question, student_answer, expected_answer):
    """Uses an LLM to check if the student's answer is correct."""
    print(f"Grading with LLM for question: {question}")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        try:
            with open('openrouter_key.txt', 'r') as keyfile:
                api_key = keyfile.read().strip()
        except FileNotFoundError:
            print("LLM grading skipped: API key file not found.", file=sys.stderr)
            return False # Default to incorrect if API key is missing

    system_prompt = """
    You are a fair and helpful AI teaching assistant. Your goal is to grade a student's answer based on their conceptual understanding.
    You will be given a question, an ideal "expected answer," and the student's actual answer.

    Your task is to evaluate if the student's answer demonstrates a core understanding of the topic. Be lenient. Do not penalize for poor grammar, spelling, or if the answer is less detailed than the expected answer, as long as the main concept is correct.

    Respond with ONLY one of two words: "correct" or "incorrect". Do not add any other text or punctuation.
    """
    
    full_prompt = f"""
    Question: "{question}"
    Expected Answer: "{expected_answer}"
    Student's Answer: "{student_answer}"
    
    Is the student's answer correct?
    """
    
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            data=json.dumps({
                "model": "mistralai/mistral-7b-instruct:free",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_prompt}
                ],
                "max_tokens": 5, # "correct" or "incorrect" is short
                "temperature": 0.1,
            }),
            timeout=15
        )
        response.raise_for_status()
        ai_response = response.json()
        result = ai_response['choices'][0]['message']['content'].strip().lower()
        print(f"LLM Grader response: {result}")
        # BUG FIX: Change from `in` to `==` to prevent "incorrect" being marked as "correct"
        return result == "correct"
    except Exception as e:
        print(f"An error occurred during LLM grading: {e}", file=sys.stderr)
        return False # Default to incorrect on error

# --- Flask Routes ---

@app.route("/")
def login():
    data = load_data()
    return render_template(
        "login.html",
        brand=data["brand"],
        avatar_initials=None,
        star_score=None,
    )

@app.route("/student")
def student():
    data = load_data()
    s = data["student"]
    lessons_with_slugs = []
    for lesson in s["lessons"]:
        lesson['slug'] = slugify(lesson['title'])
        lessons_with_slugs.append(lesson)
    
    lessons = sorted(lessons_with_slugs, key=lambda x: x["stars"], reverse=True)
    
    return render_template(
        "student.html",
        brand=data["brand"],
        avatar_initials=s.get("initials", "S"),
        star_score=s.get("star_score", 0),
        summary="Loading summary...",
        lessons=lessons,
    )

@app.route("/student/generate-summary")
def generate_student_summary():
    """Generates and returns the student AI summary."""
    data = load_data()
    s = data["student"]
    lesson_titles = ", ".join([l['title'] for l in s["lessons"]])
    system_prompt_student = "You are a helpful and encouraging assistant for a student. Briefly summarize the student's upcoming lessons for the day in one friendly and concise sentence (around 20-25 words)."
    user_prompt_student = f"My lessons for today are: {lesson_titles}. Please give me a one-sentence summary of what I'll be learning."
    
    fallback_summary = s.get("summary", "Here are your lessons for today!")
    ai_summary = generate_ai_summary(system_prompt_student, user_prompt_student, fallback_summary)
    return jsonify({"summary": ai_summary})

@app.route("/lesson/<lesson_slug>")
def lesson(lesson_slug):
    data = load_data()
    s = data["student"]
    title, content, _ = parse_lesson_file(lesson_slug)

    if title is None:
        abort(404, description="Lesson not found")

    return render_template(
        "lesson.html",
        brand=data["brand"],
        avatar_initials=s.get("initials", "S"),
        star_score=s.get("star_score", 0),
        lesson_title=title,
        lesson_content=content
    )

@app.route("/lesson/<lesson_slug>/submit", methods=["POST"])
def submit_lesson(lesson_slug):
    """Receives student answers, checks them, and returns feedback."""
    answers = request.form.to_dict()
    _, _, answer_key = parse_lesson_file(lesson_slug)

    if not answer_key:
        return jsonify({
            "status": "error", 
            "message": "Answer key not found."
        }), 404

    feedback = {}
    for question_id, user_answer in answers.items():
        rule = answer_key.get(question_id)
        if not rule:
            feedback[question_id] = "no-rule"
            continue

        is_correct = False
        grading_type = rule.get("type")

        if grading_type == "exact-match":
            correct_answer = rule.get("answer", "")
            is_correct = user_answer.strip().lower() == correct_answer.strip().lower()

        elif grading_type == "llm-check":
            question_text = rule.get("question_text", "")
            expected_answer = rule.get("expected_answer", "")
            is_correct = grade_with_llm(question_text, user_answer, expected_answer)
        
        # --- Keep old methods for backward compatibility ---
        elif "numeric" in rule:
            try:
                user_num = float(user_answer)
                correct_num = float(rule["numeric"])
                tolerance = float(rule.get("tolerance", 0.0))
                if abs(user_num - correct_num) <= tolerance:
                    is_correct = True
            except (ValueError, TypeError):
                is_correct = False
        
        elif "contains" in rule:
            keywords = rule.get("contains", [])
            min_matches = rule.get("min", 1)
            matches = sum(1 for keyword in keywords if keyword.lower() in user_answer.lower())
            if matches >= min_matches:
                is_correct = True
        
        feedback[question_id] = "correct" if is_correct else "incorrect"
    
    return jsonify({"status": "success", "feedback": feedback})


@app.route("/teacher")
def teacher():
    data = load_data()
    t = data["teacher"]
    plans_with_slugs = []
    for plan in t["plans"]:
        plan['slug'] = slugify(plan['title'])
        plans_with_slugs.append(plan)
        
    return render_template(
        "teacher.html",
        brand=data["brand"],
        avatar_initials=t.get("initials", "T"),
        star_score=None,
        summary="Loading summary...",
        students=t["students"],
        plans=plans_with_slugs,
    )

@app.route("/teacher/generate-summary")
def generate_teacher_summary():
    """Generates and returns the teacher AI summary."""
    data = load_data()
    t = data["teacher"]
    
    student_statuses = [s['status'] for s in t['students']]
    status_counts = {
        "good": student_statuses.count('good'),
        "warn": student_statuses.count('warn'),
        "bad": student_statuses.count('bad')
    }
    upcoming_plans = ", ".join([p['title'] for p in t['plans'][:2]])

    system_prompt_teacher = "You are a helpful assistant for a teacher. Concisely summarize the class status and upcoming topics in one or two brief sentences for a 'Today at a glance' section."
    user_prompt_teacher = (
        f"Here is a summary of my class: "
        f"{status_counts['good']} students are on track, "
        f"{status_counts['warn']} students need watching, and "
        f"{status_counts['bad']} students need help. "
        f"The next lesson plans are: {upcoming_plans}. "
        f"Please provide a very brief summary."
    )
    
    fallback_summary = "Review student performance and manage your lesson plans for the day."
    ai_summary = generate_ai_summary(system_prompt_teacher, user_prompt_teacher, fallback_summary)
    return jsonify({"summary": ai_summary})

@app.route("/teacher/lesson/<lesson_slug>/edit")
def edit_lesson(lesson_slug):
    data = load_data()
    t = data["teacher"]
    title, raw_markdown, raw_json = parse_raw_lesson_file(lesson_slug)

    if title is None:
        abort(404, description="Lesson not found")

    return render_template(
        "teacher_lesson_edit.html",
        brand=data["brand"],
        avatar_initials=t.get("initials", "T"),
        star_score=None,
        lesson_title=title,
        lesson_slug=lesson_slug,
        raw_markdown=raw_markdown,
        raw_json=raw_json
    )

@app.route("/teacher/lesson/<lesson_slug>/save", methods=["POST"])
def save_lesson(lesson_slug):
    """Saves the updated lesson content to its specific JSON file."""
    markdown_content = request.form.get('markdown_content')
    answer_key_json = request.form.get('answer_key_json')

    if not markdown_content or not answer_key_json:
        abort(400, "Missing content.")

    try:
        answer_key = json.loads(answer_key_json)
    except json.JSONDecodeError:
        abort(400, "Invalid JSON format for answer key.")

    title_match = re.search(r'###\s*(.*)', markdown_content)
    title = title_match.group(1).strip() if title_match else "Untitled Lesson"
    
    lesson_file = LESSONS_PATH / f"{lesson_slug}.json"
    if not lesson_file.exists():
        abort(404, "Lesson not found.")
        
    lesson_data = {
        "title": title,
        "markdown_content": markdown_content.strip(),
        "answer_key": answer_key
    }
    
    with open(lesson_file, "w", encoding="utf-8") as f:
        json.dump(lesson_data, f, indent=2)

    return redirect(url_for('teacher'))
    
@app.route("/teacher/lesson/preview", methods=["POST"])
def preview_lesson():
    """Renders markdown from a POST request and returns the HTML."""
    markdown_text = request.form.get('markdown_text', '')
    content_without_title = re.sub(r'###\s*(.*)', '', markdown_text, 1)
    html = markdown2.markdown(content_without_title)
    return html

# --- NEW AI FEATURE ROUTE ---
@app.route("/teacher/lesson/generate-with-ai", methods=["POST"])
def generate_with_ai():
    """Generates lesson content using an AI model from Openrouter."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        try:
            with open('openrouter_key.txt', 'r') as keyfile:
                api_key = keyfile.read().strip()
        except:
            return jsonify({"error": "OPENROUTER_API_KEY environment variable not set."}), 500
        
    # Get data from the frontend
    user_prompt = request.form.get('prompt')
    markdown_content = request.form.get('markdown_content')
    answer_key_json = request.form.get('answer_key_json')
    
    if not user_prompt:
        return jsonify({"error": "Prompt is missing."}), 400

    # System prompt to guide the AI
    system_prompt = """
    You are an expert educational content assistant. Your task is to create or modify a lesson plan based on the user's request.
    The lesson plan is provided as 'markdown_content' and an 'answer_key_json' string.
    You MUST return a single, valid JSON object with two keys: "markdown_content" and "answer_key_json".

    ### Answer Key Rules:
    For the `answer_key_json`, use one of two grading types:

    1.  **`exact-match`**: Use for questions with a single, precise, short answer (e.g., a number, a specific term).
        -   The `name` in the markdown MUST match the key in the answer key.
        -   Example: `"q1": {"type": "exact-match", "answer": "0.5"}`

    2.  **`llm-check`**: Use for open-ended questions that require conceptual understanding.
        -   The `name` in the markdown MUST match the key in the answer key.
        -   You MUST include the full `question_text`.
        -   You MUST provide a concise `expected_answer` for the AI grader to compare against.
        -   Example: `"q2": {"type": "llm-check", "question_text": "In your own words, what does a denominator represent?", "expected_answer": "The total number of equal parts a whole is divided into."}`

    ### Markdown Rules:
    -   The value of "markdown_content" should be the updated markdown string.
    -   Answer inputs in the markdown MUST have `class="answer-input"` and a `name` attribute (e.g., `name="q1"`).
    -   Ensure the `name` attributes in the markdown's input/textarea tags correspond perfectly to the keys in the answer key.

    Do not include any explanatory text outside of the final JSON object.
    """
    
    # User prompt that includes the teacher's request and the current lesson data
    full_prompt = f"""
    User Request: "{user_prompt}"

    Current Markdown Content:
    ```markdown
    {markdown_content}
    ```

    Current Answer Key JSON:
    ```json
    {answer_key_json}
    ```

    Please provide the updated lesson content in the specified JSON format.
    """
    
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            data=json.dumps({
                "model": "mistralai/mistral-7b-instruct:free", # Using a free model for this example
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_prompt}
                ]
            })
        )
        response.raise_for_status() # Raise an exception for bad status codes
        
        ai_response = response.json()
        content = ai_response['choices'][0]['message']['content']
        
        # Clean the response to find the JSON object
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            json_string = json_match.group(1)
        else:
            # Fallback for when the AI doesn't use markdown code blocks
            json_string = content[content.find('{'):content.rfind('}')+1]

        # Validate and parse the final JSON string
        parsed_json = json.loads(json_string)
        return jsonify(parsed_json)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"API request failed: {e}"}), 500
    except (json.JSONDecodeError, KeyError, IndexError):
        return jsonify({"error": "Failed to parse AI response. The response may be invalid."}), 500
    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {e}"}), 500

if __name__ == "__main__":
    app.run(debug=True)
