from pathlib import Path
import json
from flask import Flask, render_template, url_for

app = Flask(__name__)

DATA_PATH = Path(__file__).parent / "data" / "seed.json"

def load_data():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

@app.route("/")
def login():
    data = load_data()
    return render_template(
        "login.html",
        brand=data["brand"],
        # Hide avatar on login; header handles absence gracefully
        avatar_initials=None,
        star_score=None,
    )

@app.route("/student")
def student():
    data = load_data()
    s = data["student"]
    # Sort lessons server-side by stars (descending)
    lessons = sorted(s["lessons"], key=lambda x: x["stars"], reverse=True)
    return render_template(
        "student.html",
        brand=data["brand"],
        avatar_initials=s.get("initials", "S"),
        star_score=s.get("star_score", 0),
        summary=s.get("summary", ""),
        lessons=lessons,
    )

@app.route("/teacher")
def teacher():
    data = load_data()
    t = data["teacher"]
    plans = t["plans"]
    # Optional: sort by month/day if needed; here we keep listed order
    return render_template(
        "teacher.html",
        brand=data["brand"],
        avatar_initials=t.get("initials", "T"),
        star_score=None,  # No star pill on teacher page
        students=t["students"],
        plans=plans,
    )

if __name__ == "__main__":
    # Debug on for local development
    app.run(debug=True)