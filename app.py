import os
from flask import Flask, request, session, redirect, url_for, render_template, flash
from handlers.routes import configure_routes


app = Flask(__name__)

try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv())
except Exception as e:
    print(f"Error loading environment variables: {e}")


app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))
app.debug = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")

try:
    configure_routes(app)
except Exception as e:
    app.logger.error(f"Error configuring routes: {e}")

if __name__ == "__main__":
    app.run()