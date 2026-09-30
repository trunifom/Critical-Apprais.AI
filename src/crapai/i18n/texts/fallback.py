# PORTED from SARA-App: texts/fallback.py
# Verbatim port.
# Reference original (unchanged): reference/sara-app/texts/fallback.py
# texts/fallback.py
"""
Developer defaults that keep the app running if YAML is missing or broken.
Editors should maintain texts/en.yaml; these are safe fallbacks.

All keys mirror the structure expected by pages/review_setup.py.
Keep copy minimal but complete (no business logic here).
"""

INFO_FRAMEWORKS = (
    "**📚 Frameworks Available**  \n"
    "- **PICOS**: Population, Intervention, Comparison, Outcome, Study Design  \n"
    "- **SPIDER**: Sample, Phenomenon of Interest, Design, Evaluation, Research Type  \n"
    "- **PECO**: Population, Exposure, Comparison, Outcome  \n"
    "- **CUSTOM**: Define your own inclusion/exclusion fields  \n"
)

HELP_DATABASE_INPUT = (
    "**ℹ️ Database/Source Label**  \n"
    "Type the name of the scientific database or export source the file was downloaded from.  \n\n"
    "**Examples:**  \n"
    "- *PubMed*  \n"
    "- *MEDLINE*  \n"
    "- *Embase*  \n"
    "- *CINAHL*  \n"
    "- *Cochrane Library*  \n"
    "- *PsycINFO*  \n"
    "- *ERIC*  \n"
    "- *Scopus*  \n"
    "- *Web of Science*  \n"
    "- *Google Scholar*  \n"
)

DEFAULT_TEXTS = {
    "sections": {
        "page": {
            "title": "Automated Literature Review — Setup",
            "subtitle": "Provide project info, define screening criteria, upload your sources, and start the background review.",
        },
        "project": {
            "header": "1️⃣ Project Information",
            "fields": {
                "title": {
                    "label": "Project Title",
                    "placeholder": "e.g. Systematic review of neurofeedback in children with ADHD",
                    "help": (
                        "**ℹ️ Project Title**  \n"
                        "Give your review a concise and unique name.  \n"
                        "This will be used across logs and exported reports."
                    ),
                },
                "description": {
                    "label": "Project Description (optional)",
                    "placeholder": "Briefly describe the aim, scope and context of this review…",
                    "help": (
                        "**ℹ️ Project Description**  \n"
                        "Optionally add a short description of the study design, aims and scope.  \n"
                        "This metadata will be stored with your project and included in logs/exports."
                    ),
                },
            },
        },
        "screening": {
            "header": "2️⃣ Define Screening Criteria",
            "review_mode": {
                "label": "Select Review Mode",
                "options": ["Abstract", "Fulltext"],
                "help": (
                    "**ℹ️ Review Mode**  \n"
                    "Choose whether your automated screening will process **abstracts** or **full texts**.  \n"
                    "- *Abstract* — quick, lighter and cheaper  \n"
                    "- *Fulltext* — more detailed, higher token usage"
                ),
            },
            "objectives": {
                "count_label": "Number of objectives",
                "count_help": (
                    "**ℹ️ Research Objectives**  \n"
                    "How many objectives guide the screening?  \n"
                    "Enter a value between **1** and **10**.  \n"
                    "Each objective can be a short sentence (comma-separated sub-points are fine)."
                ),
                "list_header": "Objectives",
                "item_label": "Objective {index}",
            },
            "framework": {
                "label": "Choose framework",
                "options": ["PICOS", "SPIDER", "PECO", "CUSTOM"],
                "help": (
                    "**ℹ️ Framework Selection**  \n"
                    "Pick a standard framework to structure your inclusion/exclusion criteria, or select **CUSTOM** "
                    "to define your own fields.  \n\n"
                    "**Available Frameworks**  \n"
                    "- **PICOS**: *Population*, *Intervention*, *Comparison*, *Outcome*, *Study Design*  \n"
                    "- **SPIDER**: *Sample*, *Phenomenon of Interest*, *Design*, *Evaluation*, *Research Type*  \n"
                    "- **PECO**: *Population*, *Exposure*, *Comparison*, *Outcome*  \n"
                    "- **CUSTOM**: Define your own fields for inclusion and exclusion"
                ),
            },
            "frameworks_info": INFO_FRAMEWORKS,
            "custom_criteria": {
                "subheader": "🔧 Custom Criteria Builder",
                "field_name_label": "Enter custom field name",
                "add_button": "Add Field",
                "remove_button": "Remove",
            },
            "inclusion_exclusion": {
                "subheader": "Inclusion & Exclusion Criteria",
                "inclusion_label": "Inclusion — {field}",
                "exclusion_label": "Exclusion — {field}",
            },
        },
        "upload": {
            "abstract": {
                "header": "3️⃣ Upload & Label Source Files",
                "instructions": (
                    "Upload one or more bibliographic export files.  \n"
                    "Supported formats: **.ris**, **.bib**, and **.nbib** (PubMed/MEDLINE).  \n\n"
                    "For each uploaded file, provide the **database/source name** (e.g., *PubMed*, *MEDLINE*, *Embase*, *CINAHL*).  \n"
                    "This label will appear in your logs and help you recognize each dataset later."
                ),
                "file_type": {"label": "Select file type", "options": [".ris", ".bib", ".nbib"]},
                "file_uploader": {"label": "Choose files"},
                "database_names_header": "**Database/source label for each uploaded file:**",
                "database_field": {
                    "label": "Enter the **database/source name** for `{filename}`",
                    "placeholder": "e.g. PubMed, MEDLINE, Embase, CINAHL",
                    "help": HELP_DATABASE_INPUT,
                },
                "fulltext": {
                    "header": "3️⃣ Upload Fulltext Files",
                    "instructions": (
                        "Upload a .zip file containing the full text articles as PDFs.  \n"
                        "Supported formats: **.zip** (max. 150 MB).  \n\n"
                    ),
                    "file_type": {"label": "Select file type", "options": [".zip"]},
                    "file_uploader": {"label": "Choose files"},
                    "database_names_header": "**Database/source label for each uploaded file:**",
                },
            }
        },
        "start": {
            "confirm_label": "I confirm that the project data, criteria and uploads are correct. Start the background review.",
            "button_label": "🚀 Start Review",
            "total_records_preview": "**Total records: {count}. Preview:**",
        },
    },
    "preflight": {
        "header": "Preflight Checks (UI-only)",
        "table": {
            "headers": {
                "filename": "Filename",
                "label": "Label",
                "records": "Records",
                "with_abstract": "With Abstract",
                "status": "Status",
            }
        },
        "status": {
            "ok": "OK — file parsed successfully",
            "warn_low_abstracts": "Warning — low abstract coverage for Abstract mode",
            "error_unparseable": "Error — file could not be parsed",
            "error_no_records": "Error — file contains no records",
            "error_no_abstracts": "Error — no abstracts found for Abstract mode",
        },
        "note": (
            "*Note:* These checks are for **user feedback only**.  \n"
            "Official PRISMA counts will be computed and logged by the background worker."
        ),
    },
    "estimate": {
        "header": "Estimated Tokens & Cost (Preview)",
        "input_tokens": "Input tokens",
        "output_tokens": "Output tokens",
        "total_tokens": "Total tokens",
        "cost_range": "Estimated cost range",
        "note": (
            "*Important:* These are **estimates** for planning and transparency.  \n"
            "Actual token usage and costs depend on the model and the final prompts.  \n"
            "The background worker calculates authoritative usage."
        ),
    },
    "notifications": {
        "parse_error": "Error parsing `{filename}`: {error}",
        "review_started": "✅ Review job started. File ID: {file_id}",
        "log_failed": "Failed to log review task: {error}",
        "background_info": (
            "Your review is now running in the background and may take some time depending on system load.  \n"
            "Results and download links will be sent to **{email}**.  \n"
            "Submitted items: **{total}**."
        ),
        # (E-mail templates of the predecessor removed: the product sends no e-mail.)
    },
}
