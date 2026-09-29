"""Curated platform HR question bank (the 'approved platform HR bank'). Job-relevant behavioural and context questions only.
Every entry is checked against hr_safety in the tests. Logistics questions are built from the job posting, not invented."""

from app.services.interviews.hr_safety import is_safe_question

PLATFORM_HR = {
    "communication": [
        "Tell me about a time you had to explain a complex idea to someone without the same background. How did you approach it, and how did it go?",
        "Describe a situation where a misunderstanding happened in a project you worked on. What did you do to clear it up?",
        "How do you decide what to include when you give a status update to your team or a lead?",
        "Give an example of feedback you gave someone. How did you deliver it and what was the result?",
        "Tell me about a time you had to ask for help. How did you frame the request?",
    ],
    "collaboration": [
        "Describe a project where you depended on other people to succeed. What was your role and how did you keep the work aligned?",
        "Tell me about a time you disagreed with a teammate on how to do something. How did you reach a decision?",
        "What do you do when a teammate is falling behind on work that you depend on?",
        "Give an example of how you shared knowledge with your team.",
        "Describe how you prefer to split work when several people contribute to the same deliverable.",
    ],
    "conflict handling": [
        "Tell me about a disagreement at work or in a team project that was hard to resolve. What did you do?",
        "Describe a time you received criticism you did not agree with. How did you respond?",
        "How do you handle a situation where two people you work with want different things from you?",
        "Tell me about a deadline conflict between two tasks. How did you prioritise?",
        "What would you do if you noticed a mistake in someone else's work that was about to be released?",
    ],
    "motivation": [
        "What interests you about this role and this company?",
        "What kind of work do you find most motivating, and what would you like to learn in your first year?",
        "Describe a piece of work you are proud of and what made it satisfying.",
        "What would make you feel this role was a good fit for you after six months?",
        "Why are you looking for this type of opportunity at this stage of your career?",
    ],
    "career goals": [
        "Where would you like your skills to be in two to three years, and how does this role help?",
        "Tell me about a skill you decided to learn on your own. How did you go about it?",
        "How do you like to receive guidance and feedback while you are growing in a role?",
        "What would you want a manager or mentor to help you with in this position?",
        "Which parts of this job description do you feel least prepared for, and how would you close that gap?",
    ],
    "work preferences": [
        "How do you like to organise your day when you have several tasks with different deadlines?",
        "Do you prefer working closely with others or independently on tasks, and how do you adapt when the situation calls for the other?",
        "What kind of team environment helps you do your best work?",
        "How do you stay productive when the requirements of a task are unclear?",
        "Describe how you handle interruptions or context switching during focused work.",
    ],
}


def logistics_questions(job) -> list[str]:
    """Availability, notice, relocation and work-mode questions drawn from the posting itself."""
    out = ["When would you be able to start if you were offered this role, and is there any notice or commitment we should know about?"]
    mode = (getattr(job, "work_mode", None) or "").upper()
    city = getattr(job, "location_city", None)
    if mode == "ONSITE":
        out.append(f"This role is on-site{f' in {city}' if city else ''}. Are you able to work from that location, and would relocation be needed?")
    elif mode == "HYBRID":
        out.append(f"This role is hybrid{f', based in {city}' if city else ''}. How do you feel about splitting time between the office and home?")
    elif mode == "REMOTE":
        out.append("This role is remote. What does your working setup look like, and how do you stay connected with a distributed team?")
    et = (getattr(job, "employment_type", None) or "").upper()
    if et.startswith("INTERNSHIP"):
        dur = getattr(job, "internship_duration_value", None)
        unit = (getattr(job, "internship_duration_unit", None) or "months").lower()
        out.append(f"The internship runs for {dur} {unit}. Are you able to commit to the full duration?" if dur else
                   "Are you able to commit to the full duration of the internship?")
    if et in ("PART_TIME", "CONTRACT"):
        out.append("Are the expected hours and the length of this engagement workable for you?")
    return [q for q in out if is_safe_question(q)]
