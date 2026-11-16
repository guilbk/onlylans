import json

from pipeline import basemap, traffic

DATA = traffic.DATA_DEFAULT
OUT = traffic.build(DATA)
W, H = traffic.map_size_m(DATA)


def test_deterministic():
    assert traffic.render_js(OUT) == traffic.render_js(traffic.build(DATA))


def test_windows_and_levels():
    assert OUT["windows"] == [[8, 10], [12, 14], [17, 19]]
    assert OUT["mul"] == {"1": traffic.YELLOW_MUL, "2": traffic.RED_MUL}
    for s in OUT["segs"]:
        assert len(s["l"]) == 3 and set(s["l"]) <= {0, 1, 2} and any(s["l"])
        assert s["l"][1] in (0, 1)  # lunch jams are light: never red


def test_no_jam_at_night():
    hours = {h for a, b in OUT["windows"] for h in range(a, b)}
    assert not hours & set(range(22, 24)) and not hours & set(range(0, 6))


def test_segments_inside_the_map():
    for s in OUT["segs"]:
        p = s["p"]
        assert len(p) >= 4
        assert all(0 <= x <= W and 0 <= y <= H for x, y in zip(p[::2], p[1::2], strict=True))


def test_bridges_are_jammed():
    for b in basemap.build(DATA)["bridges"]:
        if b["name"] not in traffic.BRIDGES:
            continue
        deck = [s for s in OUT["segs"] if s["p"] == [round(v) for v in b["line"]]]
        assert deck and deck[0]["l"] == [2, 0, 2], b["name"]


def test_render_is_js_with_json_body():
    js = traffic.render_js(OUT)
    assert js.startswith(traffic.HEADER) and "PG.trafficData = " in js
    json.loads(js.split("PG.trafficData = ")[1].rstrip(";\n"))
