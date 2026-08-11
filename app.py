import json
from pathlib import Path
from uuid import uuid4

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.utils import secure_filename

from services.ai_service import (
    evaluate_socratic_answers,
    extract_concepts,
    generate_socratic_questions,
)
from services.parser_service import (
    DocumentParserError,
    clean_text,
    extract_text,
)


app = Flask(__name__)

app.config["SECRET_KEY"] = "development-secret-key"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
EXTRACTED_FOLDER = BASE_DIR / "extracted"
SESSION_FOLDER = BASE_DIR / "sessions"

UPLOAD_FOLDER.mkdir(exist_ok=True)
EXTRACTED_FOLDER.mkdir(exist_ok=True)
SESSION_FOLDER.mkdir(exist_ok=True)


ALLOWED_EXTENSIONS = {
    "pdf",
    "docx",
    "pptx",
    "txt",
}


def allowed_file(filename: str) -> bool:
    """Return True when the file extension is supported."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


def safe_session_path(session_filename):
    """
    Return a safe session path and prevent directory traversal.
    """
    safe_filename = Path(session_filename).name

    if not safe_filename.endswith(".json"):
        raise ValueError("Invalid session filename.")

    return SESSION_FOLDER / safe_filename


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    pasted_text = request.form.get(
        "material_text",
        "",
    ).strip()

    uploaded_file = request.files.get("material_file")

    extracted_text = ""
    source_name = "Pasted notes"
    file_type = "Text"

    try:
        if uploaded_file and uploaded_file.filename:
            if not allowed_file(uploaded_file.filename):
                flash(
                    "Unsupported file type. Upload PDF, DOCX, "
                    "PPTX, or TXT.",
                    "error",
                )

                return redirect(url_for("index"))

            original_filename = secure_filename(
                uploaded_file.filename
            )

            if not original_filename:
                flash(
                    "The uploaded filename is invalid.",
                    "error",
                )

                return redirect(url_for("index"))

            extension = Path(
                original_filename
            ).suffix.lower()

            unique_filename = (
                f"{Path(original_filename).stem}_"
                f"{uuid4().hex}{extension}"
            )

            saved_path = UPLOAD_FOLDER / unique_filename
            uploaded_file.save(saved_path)

            extracted_text = extract_text(str(saved_path))

            source_name = original_filename
            file_type = extension.replace(
                ".",
                "",
            ).upper()

        elif pasted_text:
            extracted_text = clean_text(pasted_text)

        else:
            flash(
                "Paste learning material or upload a document.",
                "error",
            )

            return redirect(url_for("index"))

        extracted_filename = f"{uuid4().hex}.txt"

        extracted_path = (
            EXTRACTED_FOLDER / extracted_filename
        )

        extracted_path.write_text(
            extracted_text,
            encoding="utf-8",
        )

        word_count = len(extracted_text.split())
        character_count = len(extracted_text)

        return render_template(
            "preview.html",
            material=extracted_text,
            source_name=source_name,
            file_type=file_type,
            word_count=word_count,
            character_count=character_count,
            extracted_filename=extracted_filename,
        )

    except DocumentParserError as error:
        flash(str(error), "error")
        return redirect(url_for("index"))

    except Exception as error:
        app.logger.exception(
            "Document processing failed"
        )

        flash(
            "Something went wrong while processing the "
            f"material: {error}",
            "error",
        )

        return redirect(url_for("index"))
@app.route("/concept/<session_filename>/<int:concept_index>")
def concept_page(session_filename, concept_index):
    try:
        session_path = safe_session_path(session_filename)

        if not session_path.exists():
            flash("The learning session has expired.", "error")
            return redirect(url_for("index"))

        session_data = json.loads(
            session_path.read_text(encoding="utf-8")
        )

        concepts = session_data.get("concepts", [])

        if concept_index < 0 or concept_index >= len(concepts):
            flash("Concept not found.", "error")
            return redirect(url_for("index"))

        concept = concepts[concept_index]

        return render_template(
            "concept.html",
            concept=concept,
            concept_index=concept_index,
            session_filename=session_filename,
        )

    except Exception as error:
        app.logger.exception("Concept page failed")
        flash(f"Something went wrong: {error}", "error")
        return redirect(url_for("index"))

@app.route("/extract-concepts", methods=["POST"])
def extract_material_concepts():
    extracted_filename = request.form.get(
        "extracted_filename",
        "",
    ).strip()

    if not extracted_filename:
        flash(
            "The extracted material could not be found.",
            "error",
        )

        return redirect(url_for("index"))

    safe_filename = Path(extracted_filename).name
    extracted_path = EXTRACTED_FOLDER / safe_filename

    if not extracted_path.exists():
        flash(
            "The extracted material file no longer exists.",
            "error",
        )

        return redirect(url_for("index"))

    try:
        material = extracted_path.read_text(
            encoding="utf-8"
        )

        concepts = extract_concepts(material)

        session_filename = f"{uuid4().hex}.json"
        session_path = SESSION_FOLDER / session_filename

        session_data = {
            "material": material,
            "concepts": concepts,
            "extracted_filename": safe_filename,
        }

        session_path.write_text(
            json.dumps(
                session_data,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return render_template(
            "concepts.html",
            concepts=concepts,
            session_filename=session_filename,
        )

    except Exception as error:
        app.logger.exception(
            "Concept extraction failed"
        )

        flash(
            "Something went wrong while extracting "
            f"concepts: {error}",
            "error",
        )

        return redirect(url_for("index"))


@app.route("/generate-concept-questions", methods=["POST"])
def generate_concept_questions():
    session_filename = request.form.get(
        "session_filename",
        "",
    ).strip()

    concept_index_raw = request.form.get(
        "concept_index",
        "",
    ).strip()

    if not session_filename or concept_index_raw == "":
        flash("Concept information is missing.", "error")
        return redirect(url_for("index"))

    try:
        concept_index = int(concept_index_raw)

        session_path = safe_session_path(session_filename)

        if not session_path.exists():
            flash("The learning session has expired.", "error")
            return redirect(url_for("index"))

        session_data = json.loads(
            session_path.read_text(
                encoding="utf-8"
            )
        )

        material = session_data.get(
            "material",
            "",
        )

        concepts = session_data.get(
            "concepts",
            [],
        )

        if (
            concept_index < 0
            or concept_index >= len(concepts)
        ):
            flash("Concept not found.", "error")
            return redirect(url_for("index"))

        selected_concept = concepts[
            concept_index
        ]

        learning_journey = generate_socratic_questions(
            material,
            [selected_concept],
        )

        if not learning_journey:
            flash(
                "No Socratic questions could be generated.",
                "error",
            )

            return redirect(
                url_for(
                    "concept_page",
                    session_filename=session_filename,
                    concept_index=concept_index,
                )
            )

        # Save the questions for evaluation.
        # We store both keys for compatibility.
        session_data["active_learning_journey"] = (
            learning_journey
        )

        session_data["learning_journey"] = (
            learning_journey
        )

        session_data["active_concept_index"] = (
            concept_index
        )

        session_data["active_concept"] = (
            selected_concept
        )

        session_path.write_text(
            json.dumps(
                session_data,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(
            "Saved Socratic journey:",
            len(learning_journey),
            "concept(s)"
        )

        print(
            "Session file:",
            session_filename
        )

        return render_template(
            "questions.html",
            learning_journey=learning_journey,
            session_filename=session_filename,
            concept=selected_concept,
            concept_index=concept_index,
        )

    except Exception as error:
        app.logger.exception(
            "Individual concept question generation failed"
        )

        flash(
            f"Something went wrong while generating questions: {error}",
            "error",
        )

        return redirect(url_for("index"))

@app.route("/evaluate-answers", methods=["POST"])
def evaluate_answers():
    session_filename = request.form.get(
        "session_filename",
        "",
    ).strip()

    student_answers = request.form.getlist(
        "student_answers"
    )

    if not session_filename:
        flash(
            "The learning session could not be found.",
            "error",
        )
        return redirect(url_for("index"))

    try:
        session_path = safe_session_path(
            session_filename
        )

        if not session_path.exists():
            flash(
                "The learning session has expired.",
                "error",
            )
            return redirect(url_for("index"))

        session_data = json.loads(
            session_path.read_text(
                encoding="utf-8"
            )
        )

        # First try the new individual-concept journey.
        learning_journey = session_data.get(
            "active_learning_journey",
            [],
        )

        # Backward compatibility.
        if not learning_journey:
            learning_journey = session_data.get(
                "learning_journey",
                [],
            )

        print(
            "Evaluating session:",
            session_filename
        )

        print(
            "Learning journey count:",
            len(learning_journey)
        )

        print(
            "Student answers count:",
            len(student_answers)
        )

        if not learning_journey:
            flash(
                "No Socratic questions were found for this concept.",
                "error",
            )
            return redirect(url_for("index"))

        expected_answer_count = sum(
            len(
                concept_data.get(
                    "questions",
                    [],
                )
            )
            for concept_data in learning_journey
        )

        while len(student_answers) < expected_answer_count:
            student_answers.append("")

        student_answers = [
            answer.strip()
            for answer in student_answers[
                :expected_answer_count
            ]
        ]

        evaluation_result = evaluate_socratic_answers(
            learning_journey,
            student_answers,
        )

        session_data["student_answers"] = (
            student_answers
        )

        session_data["evaluation_result"] = (
            evaluation_result
        )

        session_path.write_text(
            json.dumps(
                session_data,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return render_template(
            "results.html",
            result=evaluation_result,
            session_filename=session_filename,
            concept_index=session_data.get(
                "active_concept_index"
            ),
            concept=session_data.get(
                "active_concept"
            ),
        )

    except Exception as error:
        app.logger.exception(
            "Answer evaluation failed"
        )

        flash(
            f"Something went wrong while evaluating your answers: {error}",
            "error",
        )

        return redirect(url_for("index"))
@app.errorhandler(413)
def file_too_large(_error):
    flash(
        "The uploaded file is too large. "
        "Maximum size is 16 MB.",
        "error",
    )

    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        debug=True,
        port=5001,
    )
