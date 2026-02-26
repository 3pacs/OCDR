"""Run the OCDR Billing Reconciliation System."""

from dotenv import load_dotenv
load_dotenv()

from app import create_app

app = create_app()

if __name__ == "__main__":
    print("=" * 60)
    print("  OCDR Billing Reconciliation System")
    print("  Open in browser: http://localhost:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)
