from flask import Flask, render_template, request, redirect, url_for, session, Response
from db import init_db, seed_spots, reset_occupancy, get_conn
import models as models
import os

def create_app():
    """Create and configure the Flask app as a module."""
    app = Flask(__name__)

    #  Secret key (change this or set FLASK_SECRET_KEY in environment)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change_this_secret_key")

    # Initialize database once on startup
    with app.app_context():
        init_db()
        reset_occupancy()
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM parking_spots")
        if cur.fetchone()[0] == 0:
            seed_spots({'2W': 20, '4W': 40, 'Truck': 5, 'PD': 3})
        conn.close()

    # ---------------- ROUTES ---------------- #

    @app.route("/", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = request.form["username"].strip()
            pwd = request.form["password"].strip()
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM login_users WHERE username=? AND password=?", (user, pwd))
            row = cur.fetchone()
            if not row:
                cur.execute("SELECT * FROM login_users WHERE phone=?", (user,))
                row = cur.fetchone()
            conn.close()
            if row:
                session["user"] = row["username"] if row["username"] else row["phone"]
                return redirect(url_for("menu"))
            else:
                return render_template("login.html", error="Invalid credentials")

        return render_template("login.html")

    @app.route("/register_user", methods=["GET", "POST"])
    def register_user():
        if request.method == "POST":
            username = request.form.get("username", "").strip() or None
            password = request.form.get("password", "").strip() or None
            email = request.form.get("email", "").strip() or None
            phone = request.form.get("phone", "").strip() or None
            if not ((username and password) or phone):
                return render_template("register_user.html",
                                       error="Provide username & password OR phone number.")
            conn = get_conn()
            cur = conn.cursor()
            if username:
                cur.execute("SELECT 1 FROM login_users WHERE username=?", (username,))
                if cur.fetchone():
                    conn.close()
                    return render_template("register_user.html", error="Username already exists.")
            if phone:
                cur.execute("SELECT 1 FROM login_users WHERE phone=?", (phone,))
                if cur.fetchone():
                    conn.close()
                    return render_template("register_user.html", error="Phone already registered.")

            cur.execute("INSERT INTO login_users (username, password, email, phone) VALUES (?,?,?,?)",
                        (username, password, email, phone))
            conn.commit()
            conn.close()
            return render_template("register_user.html", msg="Registration successful! You can now log in.")
        return render_template("register_user.html")

    @app.route("/forgot_password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            email = request.form["email"].strip()
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM login_users WHERE email=?", (email,))
            row = cur.fetchone()
            if row:
                new_password = "newpass123"
                cur.execute("UPDATE login_users SET password=? WHERE id=?", (new_password, row["id"]))
                conn.commit()
                conn.close()
                return render_template("forgot_password.html",
                                       msg=f"Password reset to '{new_password}'. Please log in.")
            else:
                conn.close()
                return render_template("forgot_password.html", error="Email not found")

        return render_template("forgot_password.html")

    @app.route("/menu")
    def menu():
        if "user" not in session:
            return redirect(url_for("login"))
        return render_template("menu.html")

    @app.route("/entry", methods=["GET", "POST"])
    def entry():
        if "user" not in session:
            return redirect(url_for("login"))
        if request.method == "POST":
            vehicle_no = request.form["vehicle_no"].upper().strip()
            vtype = request.form["vehicle_type"]
            spot, info = models.vehicle_entry(vehicle_no, vtype)
            return render_template("entry.html", spot=spot, info=info, done=True)
        return render_template("entry.html")

    @app.route("/exit", methods=["GET", "POST"])
    def exit():
        if "user" not in session:
            return redirect(url_for("login"))
        if request.method == "POST":
            vehicle_no = request.form["vehicle_no"].upper().strip()
            pay_mode = request.form["payment_mode"]
            receipt, err = models.process_exit(vehicle_no, pay_mode)
            return render_template("exit.html", receipt=receipt, err=err, done=True)
        return render_template("exit.html")

    @app.route("/status")
    def status():
        if "user" not in session:
            return redirect(url_for("login"))
        rows = models.availability_summary()
        return render_template("status.html", rows=rows)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if "user" not in session:
            return redirect(url_for("login"))
        if request.method == "POST":
            mobile = request.form["mobile"].strip()
            sticker = request.form["sticker"].strip()
            vno = request.form["vehicle_no"].upper().strip()
            vtype = request.form["vehicle_type"]
            monthly_rate = float(request.form["monthly_rate"] or 0)
            models.register_user(mobile, sticker, vno, vtype, monthly_rate)
            return render_template("register.html", done=True)
        return render_template("register.html")

    @app.route("/reports")
    def reports():
        if "user" not in session:
            return redirect(url_for("login"))
        daily_summary = models.report_collection_by_day()
        monthly_summary = models.report_collection_by_month()
        daily_details = models.detailed_report_by_day()
        monthly_details = models.detailed_report_by_month()
        return render_template("reports.html",
                               daily_summary=daily_summary,
                               monthly_summary=monthly_summary,
                               daily_details=daily_details,
                               monthly_details=monthly_details)

    @app.route("/download_report/<report_type>")
    def download_report(report_type):
        if "user" not in session:
            return redirect(url_for("login"))
        if report_type == "daily":
            rows = models.report_collection_by_day()
            filename = "daily_summary.csv"
            headers = ["Date", "Total"]
            data = [(r["day"], r["total"]) for r in rows]
        elif report_type == "monthly":
            rows = models.report_collection_by_month()
            filename = "monthly_summary.csv"
            headers = ["Month", "Total"]
            data = [(r["month"], r["total"]) for r in rows]
        elif report_type == "daily_details":
            rows = models.detailed_report_by_day()
            filename = "daily_details.csv"
            headers = ["Date", "Vehicle No", "Charges", "Payment Time"]
            data = [(r["day"], r["vehicle_no"], r["charges"], r["payment_time"]) for r in rows]
        elif report_type == "monthly_details":
            rows = models.detailed_report_by_month()
            filename = "monthly_details.csv"
            headers = ["Month", "Vehicle No", "Charges", "Payment Time"]
            data = [(r["month"], r["vehicle_no"], r["charges"], r["payment_time"]) for r in rows]
        else:
            return "Invalid report type", 400

        def generate():
            yield ",".join(headers) + "\n"
            for row in data:
                yield ",".join(str(x) for x in row) + "\n"

        return Response(generate(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment;filename={filename}"})

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    return app


# 🚀 Run the app if executed directly
if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
