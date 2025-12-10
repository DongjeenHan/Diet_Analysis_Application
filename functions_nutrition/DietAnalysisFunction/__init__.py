import os
import io
import json
import csv
import azure.functions as func

# Optional local “simulated NoSQL” file (for demo)
OUTPUT_PATH = os.environ.get("SIMULATED_NOSQL_PATH", "simulated_nosql/results.json")


def _parse_float(s: str) -> float:
    """Best-effort float parse; returns 0.0 on bad/missing values."""
    try:
        if s is None:
            return 0.0
        s = str(s).strip()
        if not s:
            return 0.0
        return float(s)
    except Exception:
        return 0.0


def _clean_and_summarize(rows):
    """
    rows: list of dicts (from csv.DictReader)

    - Normalizes macro column names
    - Converts macros to float
    - Computes:
        * avg_macros_by_diet
        * recipe_counts_by_diet
    - Returns (cleaned_rows, summaries_dict)
    """
    cleaned_rows = []

    # accumulators: diet_type -> sums & count
    sums = {}
    counts = {}

    for row in rows:
        diet_type = row.get("Diet_type") or row.get("Diet Type") or "Unknown"

        # handle different header spellings
        protein_raw = row.get("Protein(g)") or row.get("Protein (g)")
        carbs_raw   = row.get("Carbs(g)")   or row.get("Carbs (g)")
        fat_raw     = row.get("Fat(g)")     or row.get("Fat (g)")

        protein = _parse_float(protein_raw)
        carbs   = _parse_float(carbs_raw)
        fat     = _parse_float(fat_raw)

        # build a new normalized row for the cleaned CSV
        cleaned_row = dict(row)  # copy all original columns
        cleaned_row["Diet_type"] = diet_type
        cleaned_row["Protein(g)"] = protein
        cleaned_row["Carbs(g)"] = carbs
        cleaned_row["Fat(g)"] = fat

        cleaned_rows.append(cleaned_row)

        # accumulators for averages
        if diet_type not in sums:
            sums[diet_type] = {"Protein(g)": 0.0, "Carbs(g)": 0.0, "Fat(g)": 0.0}
            counts[diet_type] = 0

        sums[diet_type]["Protein(g)"] += protein
        sums[diet_type]["Carbs(g)"] += carbs
        sums[diet_type]["Fat(g)"] += fat
        counts[diet_type] += 1

    # compute averages per diet
    avg_macros = {}
    for diet, total in sums.items():
        count = max(1, counts[diet])
        avg_macros[diet] = {
            "Protein(g)": total["Protein(g)"] / count,
            "Carbs(g)": total["Carbs(g)"] / count,
            "Fat(g)": total["Fat(g)"] / count,
        }

    # recipe counts per diet
    recipe_counts = {diet: counts[diet] for diet in counts}

    summaries = {
        "avg_macros_by_diet": avg_macros,
        "recipe_counts_by_diet": recipe_counts,
    }

    return cleaned_rows, summaries


def main(
    inputBlob: func.InputStream,
    cleanedBlob: func.Out[str],
    summaryBlob: func.Out[str],
):
    """
    Blob trigger: runs when All_Diets.csv changes in Blob Storage.

    Steps:
    - Read CSV rows
    - Clean data (normalize macros, convert to floats)
    - Compute averages & counts by Diet_type
    - Write:
        * Cleaned_All_Diets.csv  (via blob output binding)
        * summaries.json         (via blob output binding)
    - Also writes summaries to a local JSON file (for demo)
    """
    # 1) Read CSV from blob trigger stream
    raw_bytes = inputBlob.read()
    text = raw_bytes.decode("utf-8")

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)

    # 2) Clean and summarize
    cleaned_rows, summaries = _clean_and_summarize(rows)

    # 3) Optional: local simulated NoSQL file
    try:
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(summaries, f, indent=2)
    except Exception:
        # non-fatal in Azure
        pass

    # 4a) Write cleaned CSV to blob output
    if cleaned_rows:
        fieldnames = list(cleaned_rows[0].keys())
    else:
        fieldnames = ["Diet_type", "Protein(g)", "Carbs(g)", "Fat(g)"]

    csv_buf = io.StringIO()
    writer = csv.DictWriter(csv_buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(cleaned_rows)

    cleanedBlob.set(csv_buf.getvalue())

    # 4b) Write summaries.json to blob output
    summaryBlob.set(json.dumps(summaries))

    print(
        "Saved cleaned CSV to 'datasets/Cleaned_All_Diets.csv' and "
        "summaries to 'datasets/summaries.json'."
    )
