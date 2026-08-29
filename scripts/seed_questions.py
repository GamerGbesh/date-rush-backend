"""
Seed initial questions into the database.
"""

from app.database import SessionLocal
from app.enums import QuestionTarget
from app.models.question import Question


def seed_questions():
    db = SessionLocal()
    try:
        if db.query(Question).count() > 0:
            print("Questions already exist in the database. Skipping seed.")
            return

        questions = [
            # ANY
            Question(text="What is your idea of a perfect weekend date?", target_gender=QuestionTarget.ANY, active=True),
            Question(text="What is the most important quality you look for in a partner?", target_gender=QuestionTarget.ANY, active=True),
            Question(text="What is your biggest pet peeve in a relationship?", target_gender=QuestionTarget.ANY, active=True),
            Question(text="How do you handle disagreements with someone you care about?", target_gender=QuestionTarget.ANY, active=True),
            Question(text="What is something you are deeply passionate about?", target_gender=QuestionTarget.ANY, active=True),
            Question(text="What is your favorite travel destination and why?", target_gender=QuestionTarget.ANY, active=True),
            # MALE
            Question(text="How do you express your feelings when you really like someone?", target_gender=QuestionTarget.MALE, active=True),
            Question(text="What is one thing you wish women understood better about men?", target_gender=QuestionTarget.MALE, active=True),
            Question(text="What does commitment mean to you?", target_gender=QuestionTarget.MALE, active=True),
            # FEMALE
            Question(text="What makes you feel truly appreciated in a relationship?", target_gender=QuestionTarget.FEMALE, active=True),
            Question(text="What is one quality that immediately catches your attention?", target_gender=QuestionTarget.FEMALE, active=True),
            Question(text="How do you maintain balance between work and personal life?", target_gender=QuestionTarget.FEMALE, active=True),
        ]
        db.add_all(questions)
        db.commit()
        print(f"Successfully seeded {len(questions)} questions into the database.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_questions()
