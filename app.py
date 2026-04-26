from flask import Flask
from datetime import timedelta
import os

from routes.auth import auth_bp
from routes.main import main_bp
from routes.secretaria import secretaria_bp
from routes.coordenacao import coordenacao_bp
from routes.admin import admin_bp

app = Flask(__name__, static_folder='static', static_url_path='/static')

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_SAMESITE="Lax"
)

app.secret_key = os.getenv("SECRET_KEY")
app.permanent_session_lifetime = timedelta(hours=8)

app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)
app.register_blueprint(secretaria_bp)
app.register_blueprint(coordenacao_bp)
app.register_blueprint(admin_bp)

@app.after_request
def headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-XSS-Protection"] = "1; mode=block"
    return resp

if __name__ == "__main__":
    app.run()