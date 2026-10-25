import pytest

from agent.modules.images.image_data import Accepte

from .fakes import FakeExtracteur, FakeImageStore, FakeResultStore, Sortie


@pytest.fixture
def images():
    return FakeImageStore({("u1", "img1"): b"\xff\xd8fake"})


@pytest.fixture
def resultats():
    return FakeResultStore()


@pytest.fixture
def extracteurs():
    return {
        "ordonnance": FakeExtracteur(Accepte(Sortie())),
        "piece_identite": FakeExtracteur(Accepte(Sortie())),
    }


@pytest.fixture
def state():
    return {"user_id": "u1", "pending_image_id": "img1", "expected_image_type": "ordonnance"}
