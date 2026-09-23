from bsi_core import models as m
from sqlalchemy import update

from tests.integration.test_gaps import scene  # noqa: F401


def test_clusters_route_returns_numbers_and_briefs(client, scene):  # noqa: F811
    r = client.get(
        f"/v1/brands/{scene.brand}/clusters/gaps", headers=scene.org.headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unlabelled"] == 1
    keys = [c["key"] for c in body["clusters"]]
    assert keys[0] == "cluster:comparison:running shoes"
    gap = body["clusters"][0]
    assert gap["gap"] is True and gap["brief"]["page_type"] == "comparison page"
    assert gap["brand"]["n"] == 8 and gap["top_rival"]["name"] == "Adidas"
    assert body["clusters"][-1]["brief"] is None


def test_clusters_route_honours_filters(client, scene):  # noqa: F811
    r = client.get(
        f"/v1/brands/{scene.brand}/clusters/gaps",
        params={"prompt_ids": str(scene.vs)},
        headers=scene.org.headers,
    )
    assert [c["key"] for c in r.json()["clusters"]] == [
        "cluster:comparison:running shoes"
    ]


def test_label_route_queues_a_job(client, owner, scene):  # noqa: F811
    r = client.post(
        f"/v1/brands/{scene.brand}/prompts/label", headers=scene.org.headers
    )
    assert r.status_code == 202, r.text
    with owner() as s:
        job = s.get(m.Job, r.json()["job_id"])
    assert (job.kind, job.status) == ("label_prompts", "queued")
    again = client.post(
        f"/v1/brands/{scene.brand}/prompts/label", headers=scene.org.headers
    )
    assert again.json()["job_id"] == r.json()["job_id"]


def test_label_route_on_an_archived_brand_is_409(client, owner, scene):  # noqa: F811
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand)
            .where(m.Brand.id == scene.brand)
            .values(status="archived")
        )
    r = client.post(
        f"/v1/brands/{scene.brand}/prompts/label", headers=scene.org.headers
    )
    assert r.status_code == 409


def test_unknown_brand_is_404(client, make_org):
    org = make_org()
    zero = "00000000-0000-0000-0000-000000000000"
    assert (
        client.get(
            f"/v1/brands/{zero}/clusters/gaps", headers=org.headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/brands/{zero}/prompts/label", headers=org.headers
        ).status_code
        == 404
    )


def test_accepting_a_cluster_rec_tasks_its_prompts(client, scene):  # noqa: F811
    base = f"/v1/brands/{scene.brand}/recommendations"
    r = client.post(f"{base}/generate", headers=scene.org.headers)
    assert r.status_code == 200, r.text
    rec = next(x for x in r.json() if x["subject_key"].startswith("cluster:"))
    t = client.post(f"{base}/{rec['id']}/accept", headers=scene.org.headers)
    assert t.status_code == 201, t.text
    task = t.json()
    assert set(task["prompt_ids"]) == {str(scene.vs), str(scene.best)}
    assert task["measures_impact"] is True
