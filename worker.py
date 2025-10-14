from app import create_app, scheduler
from app import tasks

app = create_app()
tasks.init_app(app)

if __name__ == '__main__':
    with app.app_context():
        print("Starting scheduler worker...")
        # La boucle infinie est nécessaire pour que le worker ne s'arrête pas
        scheduler.start(paused=True) # On démarre en pause
        scheduler.resume() # On le relance
        while True:
            pass
