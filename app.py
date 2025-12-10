from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
load_dotenv()
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # for servers / no display
import matplotlib.pyplot as plt
import seaborn as sns
import io, base64, math, os
from datetime import datetime

from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from urllib.parse import urlparse, urljoin
from flask import abort

DATA_PATH = "All_Diets.csv"
CLEAN_PATH = "Cleaned_All_Diets.csv"

# In-memory cache so we don’t keep re-reading & re-cleaning
CACHE = {
    "source_mtime": None,           # last modified time of All_Diets.csv
    "df": None,                     # cleaned dataframe
    "avg_macros_by_diet": None,     # precomputed averages for charts
    "recipe_counts_by_diet": None,  # precomputed counts for pie chart
}


def build_cache() -> None:
    """
    Read All_Diets.csv, clean it once, compute summary results and
    store everything in the global CACHE dict. Also writes a cleaned
    copy to Cleaned_All_Diets.csv for inspection / Azure upload.
    """
    df = pd.read_csv(DATA_PATH)

    # clean numeric macro columns
    for col in ["Protein(g)", "Carbs(g)", "Fat(g)"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df[["Protein(g)", "Carbs(g)", "Fat(g)"]] = df[["Protein(g)", "Carbs(g)", "Fat(g)"]].fillna(0)

    # save cleaned copy (this simulates what your blob-trigger function would write)
    try:
        df.to_csv(CLEAN_PATH, index=False)
    except Exception:
        # not fatal if write fails locally
        pass

    # ----- precomputed results (used for charts) -----
    avg_macros = df.groupby("Diet_type")[["Protein(g)", "Carbs(g)", "Fat(g)"]].mean()
    recipe_counts = df["Diet_type"].value_counts()

    CACHE["df"] = df
    CACHE["avg_macros_by_diet"] = avg_macros
    CACHE["recipe_counts_by_diet"] = recipe_counts


def ensure_cache() -> None:
    """
    Ensure CACHE is up to date.
    If All_Diets.csv changed on disk, re-run cleaning + summary calc once.
    Otherwise reuse existing cleaned data & results.
    """
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError("All_Diets.csv not found in project root")

    src_mtime = os.path.getmtime(DATA_PATH)
    if CACHE["df"] is None or CACHE["source_mtime"] != src_mtime:
        # file changed or first load → rebuild cache once
        build_cache()
        CACHE["source_mtime"] = src_mtime


# ------------------------------
# Flask & DB setup
# ------------------------------
app = Flask(__name__)

# SECRET_KEY is required for sessions (login state)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

# Simple local DB; in Azure you’ll point this to Azure SQL / Cosmos
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",  # set this in Azure
    "sqlite:///users.db"  # fallback for local dev
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

oauth = OAuth(app)

# OAuth setup

app.config["GITHUB_CLIENT_ID"] = os.getenv("GITHUB_CLIENT_ID")
app.config["GITHUB_CLIENT_SECRET"] = os.getenv("GITHUB_CLIENT_SECRET")

oauth.register(
    name="github",
    client_id=app.config["GITHUB_CLIENT_ID"],
    client_secret=app.config["GITHUB_CLIENT_SECRET"],
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "read:user user:email"},
)


# ------------------------------
# User model
# ------------------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    provider = db.Column(db.String(50), default="local")  # e.g. local, google, github
    provider_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

# ------------------------------
# One-time DB create (run once)
# ------------------------------
with app.app_context():
    db.create_all()

# ------------------------------
# Helper: login_required decorator
# ------------------------------
from functools import wraps

def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapped_view


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
    return df[df["Diet_type"].str.lower() == diet_name.lower()]

def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return (
        test_url.scheme in ("http", "https")
        and ref_url.netloc == test_url.netloc
    )

# ------------------------------
# Auth routes
# ------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""

        if not name or not email or not password:
            flash("Please fill in all fields.", "error")
            return redirect(url_for("register"))

        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("register"))

        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("An account with this email already exists.", "error")
            return redirect(url_for("register"))

        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "error")
            return redirect(url_for("login"))

        # Store user in session
        session["user_id"] = user.id
        session["user_name"] = user.name

        return redirect(url_for("index"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ------------------------------
# Dashboard route (PROTECTED)
# ------------------------------
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    ensure_cache()
    df_all = CACHE["df"]
    action = request.form.get("action")
    selected_diet = request.form.get("dietType", "")          # from dropdown
    keyword = (request.form.get("keyword") or "").strip()     # keyword search
    page = int(request.form.get("page", "1"))                 # for recipes pagination

    charts = {}
    message = None
    total_pages = 1

    # base filtered dataframe (used by several actions)
    df_filtered = filter_by_diet(df_all, selected_diet)

    if action == "insights":
        df_filtered = filter_by_diet(df_all, selected_diet)

        # ----- 1) Bar chart: use precomputed averages -----
        avg_macros = CACHE["avg_macros_by_diet"]

        if selected_diet:
            # just the selected diet’s row (still from precomputed table)
            grp = avg_macros.loc[[selected_diet]]
        else:
            grp = avg_macros

        grp = grp.sort_values("Protein(g)", ascending=False)

        plt.figure(figsize=(6, 4))
        sns.barplot(x=grp.index, y=grp["Protein(g)"])
        plt.xticks(rotation=25, ha="right")
        plt.title("Average Protein by Diet Type")
        plt.ylabel("Protein (g)")
        charts["bar"] = fig_to_base64()

        # ----- 2) Scatter: filtered records (lightweight, not a heavy groupby) -----
        plt.figure(figsize=(5, 4))
        sns.scatterplot(
            x=df_filtered["Carbs(g)"],
            y=df_filtered["Fat(g)"],
            hue=df_filtered["Diet_type"],
            legend=False,
        )
        plt.title("Carbs vs Fat")
        plt.xlabel("Carbs (g)")
        plt.ylabel("Fat (g)")
        charts["scatter"] = fig_to_base64()

        # ----- 3) Heatmap: correlations on filtered data -----
        if df_filtered.shape[0] > 1:
            plt.figure(figsize=(4, 3))
            corr = df_filtered[["Protein(g)", "Carbs(g)", "Fat(g)"]].corr()
            sns.heatmap(corr, annot=True, cmap="coolwarm", vmin=-1, vmax=1)
            plt.title("Macro Correlations")
            charts["heatmap"] = fig_to_base64()

        # ----- 4) Pie chart: use precomputed counts when no filter -----
        if selected_diet:
            cnt = df_filtered["Diet_type"].value_counts()
        else:
            cnt = CACHE["recipe_counts_by_diet"]

        plt.figure(figsize=(4, 4))
        plt.pie(cnt.values, labels=cnt.index, autopct="%1.1f%%", startangle=140)
        plt.title("Recipe Distribution by Diet")
        charts["pie"] = fig_to_base64()

    elif action == "recipes":
        # ----- show recipes with filter + keyword + pagination -----
        rec_df = df_filtered[["Recipe_name", "Cuisine_type", "Diet_type"]].copy()

        # keyword search in recipe_name OR cuisine_type
        if keyword:
            mask = (
                rec_df["Recipe_name"].str.contains(keyword, case=False, na=False) |
                rec_df["Cuisine_type"].str.contains(keyword, case=False, na=False)
            )
            rec_df = rec_df[mask]

        per_page = 10
        total = len(rec_df)

        if total == 0:
            total_pages = 1
            page = 1
            message = ["No recipes found for your search."]
        else:
            rec_df = rec_df.sort_values("Recipe_name")
            total_pages = max(1, math.ceil(total / per_page))

            if page < 1:
                page = 1
            if page > total_pages:
                page = total_pages

            start = (page - 1) * per_page
            end = start + per_page
            sliced = rec_df.iloc[start:end]

            message = []
            for _, row in sliced.iterrows():
                recipe_name = row["Recipe_name"]
                cuisine = row["Cuisine_type"]
                diet = row["Diet_type"]
                message.append(f"{recipe_name} ({diet}, {cuisine})")

    elif action == "clusters":
        df = df_filtered.copy()
        if df.empty:
            message = ["No data for selected diet."]
        else:
            def label_row(r):
                macros = {
                    "protein": r["Protein(g)"],
                    "carbs": r["Carbs(g)"],
                    "fat": r["Fat(g)"],
                }
                return max(macros, key=macros.get)

            df["Cluster"] = df.apply(label_row, axis=1)
            counts = df["Cluster"].value_counts()
            message = [f"{k.title()} dominant: {v} recipes" for k, v in counts.items()]

    diet_options = sorted(df_all["Diet_type"].dropna().unique().tolist())
    user_name = session.get("user_name")

    return render_template(
        "insights.html",
        charts=charts,
        message=message,
        selected_diet=selected_diet,
        diet_options=diet_options,
        current_page=page,
        total_pages=total_pages,
        keyword=keyword,
        user_name=user_name
    )

@app.route("/login/github")
def login_github():
    # Where to go after login (default is dashboard)
    next_url = request.args.get("next") or url_for("index")
    if not is_safe_url(next_url):
        return abort(400)

    session["oauth_next"] = next_url
    redirect_uri = url_for("auth_github_callback", _external=True)
    return oauth.github.authorize_redirect(redirect_uri)


@app.route("/auth/github/callback")
def auth_github_callback():
    # Exchange code for access token
    token = oauth.github.authorize_access_token()

    # Get user profile from GitHub
    resp = oauth.github.get("user")
    profile = resp.json()

    # Try to get email
    email = profile.get("email")
    if not email:
        emails_resp = oauth.github.get("user/emails")
        emails_data = emails_resp.json()
        primary = [e for e in emails_data if e.get("primary") and e.get("verified")]
        if primary:
            email = primary[0].get("email")
        elif emails_data:
            email = emails_data[0].get("email")

    github_id = str(profile.get("id"))
    username = profile.get("name") or profile.get("login") or "GitHub User"
    email = (email or "").lower()

    if not email:
        flash("GitHub did not return an email address.", "error")
        return redirect(url_for("login"))

    # Look for existing GitHub user
    user = User.query.filter_by(provider="github", provider_id=github_id).first()

    # Or match by email and link
    if not user:
        user = User.query.filter_by(email=email).first()
        if user:
            user.provider = "github"
            user.provider_id = github_id
        else:
            user = User(
                name=username,
                email=email,
                provider="github",
                provider_id=github_id,
            )
            user.password_hash = ""  # no local password for pure GitHub users

        db.session.add(user)
        db.session.commit()

    # Log in
    session["user_id"] = user.id
    session["user_name"] = user.name

    next_url = session.pop("oauth_next", None) or url_for("index")
    if not is_safe_url(next_url):
        next_url = url_for("index")

    return redirect(next_url)


if __name__ == "__main__":
    app.run(debug=True)
