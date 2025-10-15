# run.py

from app import create_app, db
from app.models import User, FacebookPage, Notification, Broadcast, PublishedNews, GlobalMatchState, GlobalState, GlobalPublishedMatch

app = create_app()

from app import tasks
tasks.init_app(app)

# --- NOUVELLE SECTION : Commande pour gérer la BDD ---
@app.cli.command("create-tables")
def create_tables():
    """Crée toutes les tables de la base de données."""
    with app.app_context():
        print("Création de toutes les tables...")
        db.create_all()
        print("Tables créées avec succès !")
        print("Tables connues par SQLAlchemy :", db.metadata.tables.keys())
# --- FIN DE LA NOUVELLE SECTION ---

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)