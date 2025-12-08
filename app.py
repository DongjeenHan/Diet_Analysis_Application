from flask import Flask, render_template, request 
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # for servers / no display
import matplotlib.pyplot as plt
import seaborn as sns
import io, base64, math, os

app = Flask(__name__)

# ---- load dataset once ----
DATA_PATH = "All_Diets.csv"
if not os.path.exists(DATA_PATH):
    raise FileNotFoundError("All_Diets.csv not found in project root")

raw_df = pd.read_csv(DATA_PATH)

# normalize column names just in case
# expected columns: Diet_type, Recipe_name, Cuisine_type, Protein(g), Carbs(g), Fat(g)
# we'll keep original names but guard missing values
for col in ["Protein(g)", "Carbs(g)", "Fat(g)"]:
    if col in raw_df.columns:
        raw_df[col] = pd.to_numeric(raw_df[col], errors="coerce")
raw_df[["Protein(g)", "Carbs(g)", "Fat(g)"]] = raw_df[["Protein(g)", "Carbs(g)", "Fat(g)"]].fillna(0)

def fig_to_base64():
    """Return current Matplotlib figure as base64 string."""
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode('utf-8')
    buf.close()
    plt.close()
    return data

def filter_by_diet(df, diet_name: str):
    """Filter dataframe by diet type (case-insensitive). Empty diet_name returns original df."""
    if not diet_name:
        return df
    # some rows might have different casing
    return df[df["Diet_type"].str.lower() == diet_name.lower()]

@app.route("/", methods=["GET", "POST"])
def index():
    action = request.form.get("action")
    selected_diet = request.form.get("dietType", "")           # from dropdown
    keyword = (request.form.get("keyword") or "").strip()      # NEW: keyword search
    page = int(request.form.get("page", "1"))                  # for recipes pagination

    charts = {}
    message = None
    total_pages = 1

    # base filtered dataframe (used by several actions)
    df_filtered = filter_by_diet(raw_df, selected_diet)

    if action == "insights":
        # ----- build insights from real data -----
        # group by diet and take mean of macros
        if selected_diet:
            # when user selected a diet, show only that diet's averages
            grp = df_filtered.groupby("Diet_type")[["Protein(g)", "Carbs(g)", "Fat(g)"]].mean()
        else:
            grp = raw_df.groupby("Diet_type")[["Protein(g)", "Carbs(g)", "Fat(g)"]].mean()

        grp = grp.sort_values("Protein(g)", ascending=False)

        # 1) bar chart: average protein per diet
        plt.figure(figsize=(6, 4))
        sns.barplot(x=grp.index, y=grp["Protein(g)"])
        plt.xticks(rotation=25, ha="right")
        plt.title("Average Protein by Diet Type")
        plt.ylabel("Protein (g)")
        charts["bar"] = fig_to_base64()

        # 2) scatter: carbs vs fat for filtered records
        plt.figure(figsize=(5, 4))
        sns.scatterplot(
            x=df_filtered["Carbs(g)"],
            y=df_filtered["Fat(g)"],
            hue=df_filtered["Diet_type"],
            legend=False
        )
        plt.title("Carbs vs Fat")
        plt.xlabel("Carbs (g)")
        plt.ylabel("Fat (g)")
        charts["scatter"] = fig_to_base64()

        # 3) heatmap: correlations on filtered data
        if df_filtered.shape[0] > 1:
            plt.figure(figsize=(4, 3))
            corr = df_filtered[["Protein(g)", "Carbs(g)", "Fat(g)"]].corr()
            sns.heatmap(corr, annot=True, cmap="coolwarm", vmin=-1, vmax=1)
            plt.title("Macro Correlations")
            charts["heatmap"] = fig_to_base64()

        # 4) pie: distribution of recipes by diet (on filtered or all)
        cnt = (df_filtered if selected_diet else raw_df)["Diet_type"].value_counts()
        plt.figure(figsize=(4, 4))
        plt.pie(cnt.values, labels=cnt.index, autopct="%1.1f%%", startangle=140)
        plt.title("Recipe Distribution by Diet")
        charts["pie"] = fig_to_base64()

    elif action == "recipes":
        # ----- show real recipe names from dataset -----
        # base recipes df (already filtered by diet)
        rec_df = df_filtered[["Recipe_name", "Cuisine_type", "Diet_type"]].copy()

        # ---------- NEW: keyword search ----------
        # search in Recipe_name OR Cuisine_type (case-insensitive)
        if keyword:
            mask = (
                rec_df["Recipe_name"].str.contains(keyword, case=False, na=False) |
                rec_df["Cuisine_type"].str.contains(keyword, case=False, na=False)
            )
            rec_df = rec_df[mask]

        # ---------- Pagination ----------
        per_page = 10  # 10 recipes per page
        total = len(rec_df)

        if total == 0:
            # no matches found -> single page, friendly message
            total_pages = 1
            page = 1
            message = [ "No recipes found for your search." ]
        else:
            rec_df = rec_df.sort_values("Recipe_name")
            total_pages = max(1, math.ceil(total / per_page))

            # clamp page
            if page < 1:
                page = 1
            if page > total_pages:
                page = total_pages

            start = (page - 1) * per_page
            end = start + per_page
            sliced = rec_df.iloc[start:end]

            # build message list (kept same format as before)
            message = []
            for _, row in sliced.iterrows():
                recipe_name = row["Recipe_name"]
                cuisine = row["Cuisine_type"]
                diet = row["Diet_type"]
                message.append(f"{recipe_name} ({diet}, {cuisine})")

    elif action == "clusters":
        # ----- simple "cluster"-like summary from real data -----
        # this is not real ML clustering, but categorizes by dominant macro
        df = df_filtered.copy()
        if df.empty:
            message = ["No data for selected diet."]
        else:
            def label_row(r):
                # decide which macro is highest
                macros = {
                    "protein": r["Protein(g)"],
                    "carbs": r["Carbs(g)"],
                    "fat": r["Fat(g)"],
                }
                return max(macros, key=macros.get)

            df["Cluster"] = df.apply(label_row, axis=1)
            counts = df["Cluster"].value_counts()
            message = [f"{k.title()} dominant: {v} recipes" for k, v in counts.items()]

    # diet options to show in dropdown (unique from dataset)
    diet_options = sorted(raw_df["Diet_type"].dropna().unique().tolist())

    return render_template(
        "insights.html",
        charts=charts,
        message=message,
        selected_diet=selected_diet,
        diet_options=diet_options,
        current_page=page,
        total_pages=total_pages,   # already >= 1 in our code
        keyword=keyword            # NEW: so the input can keep its value
    )

if __name__ == "__main__":
    app.run(debug=True)
