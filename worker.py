# worker.py
from app import create_app, scheduler
from app import tasks

# Crée une instance de l'application pour avoir le contexte
app = create_app()

# Passe le contexte de l'application aux tâches
tasks.init_app(app)

# Cette ligne est la seule chose que ce script fait :
# il démarre le scheduler et le laisse tourner pour toujours.
if __name__ == '__main__':
    with app.app_context():
        print("Starting scheduler worker...")
        scheduler.start()
