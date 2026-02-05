from bot.database import Database


def test_add_and_get_vote(database: Database) -> None:
    """Добавление голоса и чтение полной структуры голоса."""
    database.add_vote(
        image_id="img1",
        vote=1,
        gallery_id="g1",
        gallery_title="Gallery 1",
        performer_ids=["p1", "p2"],
        performer_names=["Name1", "Name2"],
    )

    vote = database.get_vote("img1")
    assert vote is not None
    assert vote["image_id"] == "img1"
    assert vote["vote"] == 1
    assert vote["gallery_id"] == "g1"
    assert vote["gallery_title"] == "Gallery 1"
    assert vote["performer_ids"] == ["p1", "p2"]
    assert vote["performer_names"] == ["Name1", "Name2"]
    assert vote["voted_at"] is not None


def test_get_image_vote_status(database: Database) -> None:
    """Проверка статуса голосования: None / 1 / -1."""
    assert database.get_image_vote_status("img_unknown") is None

    database.add_vote(image_id="img_plus", vote=1)
    database.add_vote(image_id="img_minus", vote=-1)

    assert database.get_image_vote_status("img_plus") == 1
    assert database.get_image_vote_status("img_minus") == -1


def test_get_total_votes_count(database: Database) -> None:
    """Подсчет общего количества голосов, плюсов и минусов."""
    database.add_vote(image_id="img1", vote=1)
    database.add_vote(image_id="img2", vote=-1)
    database.add_vote(image_id="img3", vote=1)

    counts = database.get_total_votes_count()
    assert counts["total"] == 3
    assert counts["positive"] == 2
    assert counts["negative"] == 1
