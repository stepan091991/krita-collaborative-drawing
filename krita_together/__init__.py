from krita import Krita, DockWidgetFactory, DockWidgetFactoryBase
from .krita_together import KritaTogetherDocker, KritaTogetherExtension

app = Krita.instance()

# Создаём экземпляр докера
docker_instance = KritaTogetherDocker()

# Регистрируем докер
app.addDockWidgetFactory(
    DockWidgetFactory(
        'krita_together_docker',
        DockWidgetFactoryBase.DockRight,
        lambda: docker_instance
    )
)

# Регистрируем расширение (меню)
app.addExtension(KritaTogetherExtension(app, docker_instance))