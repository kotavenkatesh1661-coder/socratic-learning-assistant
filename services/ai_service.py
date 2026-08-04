import json
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types


load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file")


client = genai.Client(api_key=API_KEY)


MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.0-flash-lite",
]


def call_gemini(prompt, schema):
    """
    Send a structured JSON request to Gemini.

    Automatically retries and tries backup models when a model
    is temporarily unavailable.
    """
    last_error = None

    for model_name in MODELS:
        for attempt in range(3):
            try:
                print(f"Trying model: {model_name}")

                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_json_schema=schema,
                        temperature=0.5,
                        max_output_tokens=8192,
                    ),
                )

                if not response.text:
                    raise ValueError("Gemini returned an empty response.")

                return json.loads(response.text)

            except errors.ServerError as error:
                last_error = error

                if attempt < 2:
                    wait_time = 4 * (attempt + 1)

                    print(
                        f"{model_name} is busy. "
                        f"Retrying in {wait_time} seconds..."
                    )

                    time.sleep(wait_time)

            except errors.ClientError as error:
                last_error = error

                print(
                    f"{model_name} is unavailable. "
                    "Trying another model..."
                )

                break

            except json.JSONDecodeError as error:
                raise ValueError(
                    "Gemini returned invalid JSON."
                ) from error

    raise RuntimeError(
        "All Gemini models are currently unavailable. "
        "Please try again shortly."
    ) from last_error


def extract_concepts(text):
    """
    Extract every meaningful concept found in the learning material.

    The function does not impose a fixed 8–12 concept limit.
    """
    if not text or not text.strip():
        raise ValueError("Learning material cannot be empty.")

    prompt = f"""
You are an educational content analyst.

Read the complete learning material below and identify ALL meaningful
learning concepts contained in it.

Important instructions:

- Do not limit the result to 8, 10, or 12 concepts.
- Include every distinct concept that is important for understanding
  the supplied material.
- Do not combine unrelated concepts merely to reduce the number.
- Do not create duplicate concepts.
- Do not include headings that contain no educational meaning.
- Use the amount of detail in the material to determine how many
  concepts are needed.
- A short passage may contain only a few concepts.
- A long chapter may contain dozens of concepts.
- Preserve both major concepts and important supporting concepts.
- Return concepts in the same general order in which they appear
  in the learning material.

For every concept provide:

1. A clear and concise concept name.
2. A one- or two-sentence description explaining the concept based
   on the supplied material.

Learning material:

{text}
"""

    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "concept": {
                    "type": "string",
                },
                "description": {
                    "type": "string",
                },
            },
            "required": [
                "concept",
                "description",
            ],
        },
    }

    concepts = call_gemini(
        prompt,
        schema,
    )

    if not concepts:
        raise ValueError(
            "No concepts were identified in the learning material."
        )

    # Remove accidental duplicates while preserving order.
    unique_concepts = []
    seen_concepts = set()

    for concept_data in concepts:
        concept_name = concept_data.get(
            "concept",
            "",
        ).strip()

        description = concept_data.get(
            "description",
            "",
        ).strip()

        if not concept_name:
            continue

        normalized_name = concept_name.casefold()

        if normalized_name in seen_concepts:
            continue

        seen_concepts.add(normalized_name)

        unique_concepts.append(
            {
                "concept": concept_name,
                "description": description,
            }
        )

    if not unique_concepts:
        raise ValueError(
            "No valid concepts were identified."
        )

    print(
        f"Extracted {len(unique_concepts)} concepts "
        "from the learning material."
    )

    return unique_concepts


def generate_socratic_questions(material, concepts):
    if not material or not material.strip():
        raise ValueError("Learning material cannot be empty.")

    if not concepts:
        raise ValueError("No concepts were provided.")

    concepts_text = json.dumps(
        concepts,
        indent=2,
        ensure_ascii=False,
    )

    prompt = f"""
You are a creative Socratic tutor.

Your purpose is not to immediately tell students the answer.
Guide students toward understanding by asking thoughtful,
progressive questions.

Use the original material and extracted concepts below.

For every concept, create a five-stage learning journey:

1. Explore
   Ask a simple question that connects the concept to something
   familiar or activates prior knowledge.

2. Reason
   Ask a deeper question about how or why the concept works.

3. Challenge
   Present a misconception, contradiction, comparison, or
   surprising scenario that forces the learner to think carefully.

4. Apply
   Give a realistic mini-scenario where the learner must use
   the concept.

5. Reflect
   Ask the learner to explain the concept in their own words or
   connect it to another idea.

For each question include:

- stage
- question
- hint
- sample_answer

Make questions clear, creative, educational, and appropriate for
a university student.

Hints should guide without directly revealing the answer.

Sample answers should be concise explanations, not merely one-word
responses.

Original learning material:

{material}

Extracted concepts:

{concepts_text}
"""

    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "concept": {
                    "type": "string"
                },
                "description": {
                    "type": "string"
                },
                "questions": {
                    "type": "array",
                    "minItems": 5,
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "stage": {
                                "type": "string"
                            },
                            "question": {
                                "type": "string"
                            },
                            "hint": {
                                "type": "string"
                            },
                            "sample_answer": {
                                "type": "string"
                            },
                        },
                        "required": [
                            "stage",
                            "question",
                            "hint",
                            "sample_answer",
                        ],
                    },
                },
            },
            "required": [
                "concept",
                "description",
                "questions",
            ],
        },
    }

    return call_gemini(prompt, schema)
def evaluate_socratic_answers(learning_journey, student_answers):
    if not learning_journey:
        raise ValueError("Learning journey is missing.")

    questions_for_review = []
    answer_index = 0

    for concept_data in learning_journey:
        concept_name = concept_data.get("concept", "Unknown concept")

        for question_data in concept_data.get("questions", []):
            submitted_answer = ""

            if answer_index < len(student_answers):
                submitted_answer = student_answers[answer_index].strip()

            questions_for_review.append(
                {
                    "concept": concept_name,
                    "stage": question_data.get("stage", ""),
                    "question": question_data.get("question", ""),
                    "reference_answer": question_data.get(
                        "sample_answer",
                        "",
                    ),
                    "student_answer": submitted_answer,
                }
            )

            answer_index += 1

    review_data = json.dumps(
        questions_for_review,
        indent=2,
        ensure_ascii=False,
    )

    prompt = f"""
You are an encouraging university-level Socratic learning evaluator.

Evaluate each student response using this rubric:

0 = No response or completely unrelated
1 = Minimal understanding
2 = Partial understanding with important gaps
3 = Good understanding with minor gaps
4 = Strong, accurate, and well-reasoned understanding

Important evaluation rules:

- Reward correct reasoning even when wording differs from the reference.
- Do not require the student to copy the sample answer.
- Give constructive and encouraging feedback.
- Identify one specific strength.
- Identify one specific improvement.
- Keep feedback concise.
- Do not unfairly penalize grammar.

Student responses and reference material:

{review_data}
"""

    schema = {
        "type": "object",
        "properties": {
            "evaluations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "concept": {
                            "type": "string"
                        },
                        "stage": {
                            "type": "string"
                        },
                        "question": {
                            "type": "string"
                        },
                        "student_answer": {
                            "type": "string"
                        },
                        "score": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 4,
                        },
                        "feedback": {
                            "type": "string"
                        },
                        "strength": {
                            "type": "string"
                        },
                        "improvement": {
                            "type": "string"
                        },
                    },
                    "required": [
                        "concept",
                        "stage",
                        "question",
                        "student_answer",
                        "score",
                        "feedback",
                        "strength",
                        "improvement",
                    ],
                },
            },
            "overall_feedback": {
                "type": "string"
            },
        },
        "required": [
            "evaluations",
            "overall_feedback",
        ],
    }

    result = call_gemini(prompt, schema)

    evaluations = result.get("evaluations", [])

    earned_score = sum(
        evaluation.get("score", 0)
        for evaluation in evaluations
    )

    maximum_score = len(evaluations) * 4

    percentage = (
        round((earned_score / maximum_score) * 100)
        if maximum_score > 0
        else 0
    )

    if percentage >= 90:
        learning_level = "Excellent Understanding"
    elif percentage >= 75:
        learning_level = "Strong Understanding"
    elif percentage >= 60:
        learning_level = "Developing Understanding"
    elif percentage >= 40:
        learning_level = "Basic Understanding"
    else:
        learning_level = "Needs More Practice"

    result["earned_score"] = earned_score
    result["maximum_score"] = maximum_score
    result["percentage"] = percentage
    result["learning_level"] = learning_level

    return result