import os
import re
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path
from uuid import uuid4

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "lost_and_found.db"
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
BUILDINGS = ("TT", "SJT", "PRP")
SUPER_ADMIN = "super_admin"
COORDINATOR = "coordinator"

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-before-production"),
    UPLOAD_FOLDER=str(UPLOAD_FOLDER),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def add_column_if_missing(db, table, column, definition):
    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    """Create the schema and safely migrate databases made by earlier versions."""
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'super_admin',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            description TEXT,
            building TEXT NOT NULL CHECK (building IN ('TT', 'SJT', 'PRP')),
            submitted_at TEXT NOT NULL,
            image_filename TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Available' CHECK (status IN ('Available', 'Collected')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            admin_id INTEGER NOT NULL,
            FOREIGN KEY (admin_id) REFERENCES admins(id)
        );

        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL UNIQUE,
            register_number TEXT NOT NULL,
            collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_by INTEGER NOT NULL,
            FOREIGN KEY (item_id) REFERENCES items(id),
            FOREIGN KEY (processed_by) REFERENCES admins(id)
        );

        CREATE TABLE IF NOT EXISTS claimed_objects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL UNIQUE,
            student_name TEXT NOT NULL,
            register_number TEXT NOT NULL,
            email TEXT NOT NULL,
            claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES items(id)
        );
        """
    )
    # Earlier one-role databases get a Super Admin role without losing records.
    add_column_if_missing(db, "admins", "role", "TEXT NOT NULL DEFAULT 'super_admin'")
    add_column_if_missing(db, "admins", "is_active", "INTEGER NOT NULL DEFAULT 1")
    db.execute("UPDATE admins SET role = ? WHERE role IS NULL OR role = ''", (SUPER_ADMIN,))
    db.execute("UPDATE admins SET is_active = 1 WHERE is_active IS NULL")

    accounts = (
        ("admin", "admin123", SUPER_ADMIN),
        ("coordinator", "coordinator123", COORDINATOR),
    )
    for admin_id, password, role in accounts:
        exists = db.execute("SELECT id FROM admins WHERE admin_id = ?", (admin_id,)).fetchone()
        if not exists:
            db.execute(
                "INSERT INTO admins (admin_id, password_hash, role) VALUES (?, ?, ?)",
                (admin_id, generate_password_hash(password), role),
            )
    db.commit()
    db.close()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("coordinator_login"))
        account = get_db().execute(
            "SELECT role, is_active FROM admins WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if not account or not account["is_active"] or account["role"] != session.get("user_role"):
            session.clear()
            flash("Your account is no longer active. Please sign in again.", "warning")
            return redirect(url_for("student_items"))
        return view(*args, **kwargs)

    return wrapped_view


def role_required(role):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped_view(*args, **kwargs):
            if session.get("user_role") != role:
                flash("Your account does not have permission to open that portal.", "danger")
                return portal_home()
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def portal_home():
    if session.get("user_role") == SUPER_ADMIN:
        return redirect(url_for("super_admin_dashboard"))
    if session.get("user_role") == COORDINATOR:
        return redirect(url_for("coordinator_dashboard"))
    return redirect(url_for("student_items"))


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def parse_item_form(require_image):
    item_name = request.form.get("item_name", "").strip()
    description = request.form.get("description", "").strip()
    building = request.form.get("building", "")
    submitted_at = request.form.get("submitted_at", "")
    image = request.files.get("image")
    if not item_name or building not in BUILDINGS or not submitted_at:
        return None, "Please complete the required item details."
    if require_image and (not image or not image.filename):
        return None, "Please select an image for the item."
    if image and image.filename and not allowed_file(image.filename):
        return None, "Use a PNG, JPG, JPEG, GIF, or WEBP image."
    try:
        submitted_at = datetime.fromisoformat(submitted_at).isoformat(timespec="minutes")
    except ValueError:
        return None, "Please enter a valid date and time."
    return (item_name, description, building, submitted_at, image), None


def claim_details_from_form():
    student_name = request.form.get("student_name", "").strip()
    register_number = request.form.get("register_number", "").strip().upper()
    email = request.form.get("email", "").strip().lower()
    if not student_name or not register_number or not email:
        return None, "Please enter the student's name, register number, and email address."
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return None, "Please enter a valid email address."
    return (student_name, register_number, email), None


def save_claim(db, item_id, details):
    db.execute(
        "INSERT INTO claimed_objects (item_id, student_name, register_number, email) VALUES (?, ?, ?, ?)",
        (item_id, *details),
    )
    db.commit()


def item_with_claim(db, item_id):
    return db.execute(
        """
        SELECT i.*, co.id AS claim_id
        FROM items i LEFT JOIN claimed_objects co ON co.item_id = i.id
        WHERE i.id = ?
        """,
        (item_id,),
    ).fetchone()


def dashboard_items(db):
    return db.execute(
        """
        SELECT i.*, creator.admin_id AS added_by,
               c.register_number AS collection_register_number, c.collected_at,
               processor.admin_id AS collected_by,
               co.student_name AS claimant_name, co.register_number AS claimant_register_number,
               co.email AS claimant_email, co.claimed_at
        FROM items i
        LEFT JOIN admins creator ON creator.id = i.admin_id
        LEFT JOIN collections c ON c.item_id = i.id
        LEFT JOIN admins processor ON processor.id = c.processed_by
        LEFT JOIN claimed_objects co ON co.item_id = i.id
        ORDER BY CASE WHEN i.status = 'Available' AND co.id IS NULL THEN 0
                      WHEN i.status = 'Available' THEN 1 ELSE 2 END, i.submitted_at DESC
        """
    ).fetchall()


def item_counts(db):
    return db.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(status = 'Available' AND NOT EXISTS (SELECT 1 FROM claimed_objects co WHERE co.item_id = items.id)) AS available,
               SUM(status = 'Available' AND EXISTS (SELECT 1 FROM claimed_objects co WHERE co.item_id = items.id)) AS claimed,
               SUM(status = 'Collected') AS collected
        FROM items
        """
    ).fetchone()


@app.template_filter("display_datetime")
def display_datetime(value):
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y, %I:%M %p")
    except ValueError:
        return value


@app.route("/")
def index():
    return redirect(url_for("student_items"))


@app.route("/items")
def student_items():
    building = request.args.get("building", "")
    search = request.args.get("search", "").strip()
    db = get_db()
    query = """
        SELECT i.* FROM items i
        WHERE i.status = 'Available'
          AND NOT EXISTS (SELECT 1 FROM claimed_objects co WHERE co.item_id = i.id)
    """
    values = []
    if building in BUILDINGS:
        query += " AND building = ?"
        values.append(building)
    if search:
        query += " AND (item_name LIKE ? OR description LIKE ?)"
        values.extend([f"%{search}%", f"%{search}%"])
    items = db.execute(query + " ORDER BY submitted_at DESC", values).fetchall()
    return render_template("student_items.html", items=items, buildings=BUILDINGS, selected_building=building, search=search)


def sign_in(role, portal_name, demo_id, demo_password):
    if session.get("user_id"):
        return portal_home()
    if request.method == "POST":
        admin_id = request.form.get("admin_id", "").strip()
        password = request.form.get("password", "")
        account = get_db().execute(
            "SELECT * FROM admins WHERE admin_id = ? AND role = ? AND is_active = 1",
            (admin_id, role),
        ).fetchone()
        if account and check_password_hash(account["password_hash"], password):
            session.clear()
            session["user_id"] = account["id"]
            session["user_name"] = account["admin_id"]
            session["user_role"] = account["role"]
            return portal_home()
        flash(f"Invalid {portal_name} ID or password.", "danger")
    return render_template("role_login.html", portal_name=portal_name, demo_id=demo_id, demo_password=demo_password)


@app.route("/admin/login", methods=["GET", "POST"])
def super_admin_login():
    return sign_in(SUPER_ADMIN, "Super Admin", "admin", "admin123")


@app.route("/coordinator/login", methods=["GET", "POST"])
def coordinator_login():
    return sign_in(COORDINATOR, "Coordinator", "coordinator", "coordinator123")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("student_items"))


@app.route("/admin")
@role_required(SUPER_ADMIN)
def super_admin_dashboard():
    db = get_db()
    coordinators = db.execute(
        "SELECT id, admin_id, is_active, created_at FROM admins WHERE role = ? ORDER BY created_at DESC",
        (COORDINATOR,),
    ).fetchall()
    return render_template(
        "super_admin_dashboard.html",
        counts=item_counts(db),
        coordinators=coordinators,
        items=dashboard_items(db),
    )


@app.route("/admin/coordinators", methods=["POST"])
@role_required(SUPER_ADMIN)
def create_coordinator():
    admin_id = request.form.get("admin_id", "").strip()
    password = request.form.get("password", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", admin_id):
        flash("Coordinator ID must be 3-30 letters, numbers, dots, dashes, or underscores.", "danger")
    elif len(password) < 8:
        flash("Coordinator password must contain at least 8 characters.", "danger")
    else:
        try:
            db = get_db()
            db.execute(
                "INSERT INTO admins (admin_id, password_hash, role) VALUES (?, ?, ?)",
                (admin_id, generate_password_hash(password), COORDINATOR),
            )
            db.commit()
            flash("Coordinator account created.", "success")
        except sqlite3.IntegrityError:
            flash("That ID is already in use.", "danger")
    return redirect(url_for("super_admin_dashboard"))


@app.route("/admin/coordinators/<int:coordinator_id>/toggle", methods=["POST"])
@role_required(SUPER_ADMIN)
def toggle_coordinator(coordinator_id):
    db = get_db()
    coordinator = db.execute("SELECT * FROM admins WHERE id = ? AND role = ?", (coordinator_id, COORDINATOR)).fetchone()
    if not coordinator:
        flash("Coordinator account not found.", "danger")
    else:
        db.execute("UPDATE admins SET is_active = ? WHERE id = ?", (0 if coordinator["is_active"] else 1, coordinator_id))
        db.commit()
        flash(f"Coordinator account {'activated' if not coordinator['is_active'] else 'deactivated'}.", "success")
    return redirect(url_for("super_admin_dashboard"))


@app.route("/admin/coordinators/<int:coordinator_id>/edit", methods=["POST"])
@role_required(SUPER_ADMIN)
def update_coordinator(coordinator_id):
    admin_id = request.form.get("admin_id", "").strip()
    password = request.form.get("password", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", admin_id):
        flash("Coordinator ID must be 3-30 letters, numbers, dots, dashes, or underscores.", "danger")
        return redirect(url_for("super_admin_dashboard"))
    db = get_db()
    coordinator = db.execute("SELECT id FROM admins WHERE id = ? AND role = ?", (coordinator_id, COORDINATOR)).fetchone()
    if not coordinator:
        flash("Coordinator account not found.", "danger")
        return redirect(url_for("super_admin_dashboard"))
    duplicate = db.execute("SELECT id FROM admins WHERE admin_id = ? AND id != ?", (admin_id, coordinator_id)).fetchone()
    if duplicate:
        flash("That ID is already in use.", "danger")
    elif password and len(password) < 8:
        flash("New password must contain at least 8 characters.", "danger")
    else:
        if password:
            db.execute(
                "UPDATE admins SET admin_id = ?, password_hash = ? WHERE id = ?",
                (admin_id, generate_password_hash(password), coordinator_id),
            )
        else:
            db.execute("UPDATE admins SET admin_id = ? WHERE id = ?", (admin_id, coordinator_id))
        db.commit()
        flash("Coordinator account updated.", "success")
    return redirect(url_for("super_admin_dashboard"))


@app.route("/admin/coordinators/<int:coordinator_id>/delete", methods=["POST"])
@role_required(SUPER_ADMIN)
def delete_coordinator(coordinator_id):
    db = get_db()
    coordinator = db.execute("SELECT admin_id FROM admins WHERE id = ? AND role = ?", (coordinator_id, COORDINATOR)).fetchone()
    if not coordinator:
        flash("Coordinator account not found.", "danger")
    else:
        references = db.execute(
            "SELECT (SELECT COUNT(*) FROM items WHERE admin_id = ?) + (SELECT COUNT(*) FROM collections WHERE processed_by = ?)",
            (coordinator_id, coordinator_id),
        ).fetchone()[0]
        if references:
            flash("This Coordinator has audit records and cannot be deleted. Deactivate the account instead.", "warning")
        else:
            db.execute("DELETE FROM admins WHERE id = ?", (coordinator_id,))
            db.commit()
            flash(f"Coordinator '{coordinator['admin_id']}' deleted.", "success")
    return redirect(url_for("super_admin_dashboard"))


@app.route("/coordinator")
@role_required(COORDINATOR)
def coordinator_dashboard():
    db = get_db()
    return render_template("coordinator_dashboard.html", items=dashboard_items(db), counts=item_counts(db), buildings=BUILDINGS)


@app.route("/coordinator/items", methods=["POST"])
@role_required(COORDINATOR)
def add_item():
    form_data, error = parse_item_form(require_image=True)
    if error:
        flash(error, "danger")
        return redirect(url_for("coordinator_dashboard"))
    item_name, description, building, submitted_at, image = form_data
    filename = f"{uuid4().hex}_{secure_filename(image.filename)}"
    image.save(UPLOAD_FOLDER / filename)
    db = get_db()
    db.execute(
        """INSERT INTO items (item_name, description, building, submitted_at, image_filename, admin_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (item_name, description, building, submitted_at, filename, session["user_id"]),
    )
    db.commit()
    flash("Item has been added to the public lost & found board.", "success")
    return redirect(url_for("coordinator_dashboard"))


def edit_item_page(item_id, dashboard_endpoint):
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        flash("Item not found.", "danger")
        return redirect(url_for(dashboard_endpoint))
    if request.method == "POST":
        form_data, error = parse_item_form(require_image=False)
        if error:
            flash(error, "danger")
            return redirect(request.url)
        item_name, description, building, submitted_at, image = form_data
        filename = item["image_filename"]
        if image and image.filename:
            filename = f"{uuid4().hex}_{secure_filename(image.filename)}"
            image.save(UPLOAD_FOLDER / filename)
        db.execute(
            """UPDATE items SET item_name = ?, description = ?, building = ?, submitted_at = ?, image_filename = ?
               WHERE id = ?""",
            (item_name, description, building, submitted_at, filename, item_id),
        )
        db.commit()
        flash("Item details updated.", "success")
        return redirect(url_for(dashboard_endpoint))
    return render_template("edit_item.html", item=item, buildings=BUILDINGS, dashboard_endpoint=dashboard_endpoint)


@app.route("/coordinator/items/<int:item_id>/edit", methods=["GET", "POST"])
@role_required(COORDINATOR)
def edit_item(item_id):
    return edit_item_page(item_id, "coordinator_dashboard")


@app.route("/admin/items/<int:item_id>/edit", methods=["GET", "POST"])
@role_required(SUPER_ADMIN)
def super_admin_edit_item(item_id):
    return edit_item_page(item_id, "super_admin_dashboard")


@app.route("/admin/items/<int:item_id>/delete", methods=["POST"])
@role_required(SUPER_ADMIN)
def delete_item(item_id):
    db = get_db()
    item = db.execute("SELECT image_filename, item_name FROM items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        flash("Item not found.", "danger")
        return redirect(url_for("super_admin_dashboard"))

    # Delete dependent audit rows first because they reference the item record.
    db.execute("DELETE FROM collections WHERE item_id = ?", (item_id,))
    db.execute("DELETE FROM claimed_objects WHERE item_id = ?", (item_id,))
    db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    db.commit()

    image_path = (UPLOAD_FOLDER / item["image_filename"]).resolve()
    uploads_path = UPLOAD_FOLDER.resolve()
    try:
        if image_path.is_relative_to(uploads_path) and image_path.is_file():
            image_path.unlink()
    except OSError:
        # The database deletion remains valid if an old image file is already absent or locked.
        pass
    flash(f"Item '{item['item_name']}' and its linked claim/collection records were permanently deleted.", "success")
    return redirect(url_for("super_admin_dashboard"))


@app.route("/coordinator/items/<int:item_id>/claim", methods=["POST"])
@role_required(COORDINATOR)
def record_claim(item_id):
    db = get_db()
    item = item_with_claim(db, item_id)
    if not item or item["status"] != "Available" or item["claim_id"]:
        flash("This item is no longer available for a claim.", "warning")
        return redirect(url_for("coordinator_dashboard"))
    details, error = claim_details_from_form()
    if error:
        flash(error, "danger")
    else:
        try:
            save_claim(db, item_id, details)
            flash("Claim recorded. The item is no longer public.", "success")
        except sqlite3.IntegrityError:
            flash("This item was just claimed by another student.", "warning")
    return redirect(url_for("coordinator_dashboard"))


@app.route("/coordinator/items/<int:item_id>/collect", methods=["POST"])
@role_required(COORDINATOR)
def collect_item(item_id):
    register_number = request.form.get("register_number", "").strip().upper()
    if not register_number:
        flash("Enter the student's register number before recording collection.", "danger")
        return redirect(url_for("coordinator_dashboard"))
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        flash("Item not found.", "danger")
    elif item["status"] == "Collected":
        flash("This item has already been marked as collected.", "warning")
    else:
        db.execute("UPDATE items SET status = 'Collected' WHERE id = ?", (item_id,))
        db.execute(
            "INSERT INTO collections (item_id, register_number, processed_by) VALUES (?, ?, ?)",
            (item_id, register_number, session["user_id"]),
        )
        db.commit()
        flash("Collection recorded. The claim and handover history are retained for security.", "success")
    return redirect(url_for("coordinator_dashboard"))


@app.errorhandler(413)
def too_large(_error):
    flash("Image is too large. The maximum upload size is 5 MB.", "danger")
    return redirect(request.referrer or url_for("student_items"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
