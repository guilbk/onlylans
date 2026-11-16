from pipeline import balance as b

SPEED = 36.0  # km/h, flat: 10 m/s
FLAT = tuple([SPEED] * 24)


def order(i: int, t: float, x: float, y: float = 0.0, d: float = 60.0, fare: float = 5.0,
          c: int = 2) -> b.Order:
    return b.Order(i, t, x, y, (x, x + 100), (y, y), d, fare, c)


def shift(orders: list[b.Order], ranking: tuple[float, ...] = (10.0, 6.0, 2.0)) -> b.Shift:
    orders.sort(key=lambda o: o.t)
    return b.Shift("t", 8, ranking, 6.0, 10.0, ranking[0], FLAT, 1.0, tuple(orders),
                   tuple(o.t for o in orders))


def decoy(o: b.Order) -> b.Order:
    """Mirror of ``o`` around HOME at t=1: keeps the demand centre at HOME (bot stays put)."""
    return order(99, 1, 2 * b.HOME[0] - o.x0, 2 * b.HOME[1] - o.y0)


def with_decoy(o: b.Order) -> list[b.Order]:
    return [o, decoy(o)]


def play(sh: b.Shift, lag: float = 0.0, strategy: str = "value", diff: str = "normal") -> float:
    return b.play_shift(sh, b.Params(diff, strategy, lag))


def at_home(dx: float) -> float:
    return b.HOME[0] + dx


def test_exactly_on_time_is_reachable() -> None:
    # 1000 m at 10 m/s = 100 s + 30 s boarding
    assert play(shift(with_decoy(order(0, 130, at_home(1000), b.HOME[1])))) == 5.0
    assert play(shift(with_decoy(order(0, 129, at_home(1000), b.HOME[1])))) == 0.0


def test_outside_radius_is_invisible() -> None:
    far = order(0, 2000, at_home(2600), b.HOME[1])  # street hail radius 2500 m
    assert play(shift(with_decoy(far))) == 0.0
    assert play(shift(with_decoy(far)), diff="easy") == 5.0  # radius 3125 m


def test_lag_hides_pin() -> None:
    o = order(0, 130, at_home(1000), b.HOME[1], c=2)  # appears at 130 - 420 < 0, always visible
    assert play(shift(with_decoy(o)), lag=0.0) == 5.0
    assert play(shift(with_decoy(o)), lag=1000.0) == 0.0


def test_lag_makes_pin_unreachable_but_visible() -> None:
    o = order(0, 1000, at_home(1000), b.HOME[1])  # appears at 580
    assert play(shift(with_decoy(o)), lag=0.0) == 5.0
    assert play(shift(with_decoy(o)), lag=250.0) == 5.0  # noticed at 830, eta 130 -> 960 <= 1000
    assert play(shift(with_decoy(o)), lag=300.0) == 0.0  # noticed at 880, 1010 > 1000


def test_booking_while_riding() -> None:
    first = order(0, 50, at_home(0), b.HOME[1], d=600.0)  # picked up at 30, ride ends 630
    # drop-off at x+100; next pickup 1000 m beyond it: eta 100 + 30 = 130 s after ride end
    second = order(1, 30 + 600 + 130, at_home(1100), b.HOME[1], fare=7.0)
    assert play(shift([first, second])) == 12.0
    late = order(1, 30 + 600 + 129, at_home(1100), b.HOME[1], fare=7.0)
    assert play(shift([first, late])) == 5.0


def test_strategies_differ() -> None:
    near = order(0, 300, at_home(100), b.HOME[1], d=600.0, fare=4.0)
    rich = order(1, 300, at_home(500), b.HOME[1], d=60.0, fare=9.0)
    sh = shift([near, rich])
    assert play(sh, strategy="nearest") == 4.0
    assert play(sh, strategy="value") == 13.0


def test_medal_boundaries() -> None:
    sh = shift([], ranking=(10.0, 8.0, 6.0, 4.0, 2.0))
    sh = b.Shift(sh.id, 8, sh.ranking, 6.0, 8.0, 10.0, FLAT, 1.0, (), ())
    assert b.medal_for(12.5, sh) == 4
    assert b.medal_for(12.49, sh) == 3
    assert b.medal_for(10.0, sh) == 2
    assert b.medal_for(10.01, sh) == 3
    assert b.medal_for(8.0, sh) == 2
    assert b.medal_for(7.99, sh) == 1
    assert b.medal_for(6.0, sh) == 1
    assert b.medal_for(5.99, sh) == 0


def test_rank_counts_strictly_more() -> None:
    sh = shift([], ranking=(10.0, 8.0, 8.0, 2.0))
    assert b.rank_among(8.0, sh) == 2
    assert b.rank_among(11.0, sh) == 1
    assert b.rank_among(0.0, sh) == 5


def test_deterministic() -> None:
    orders = [order(i, 100 + 40 * i, at_home(300 * (i % 5)), b.HOME[1] + 50 * i) for i in range(30)]
    sh = shift(orders)
    assert play(sh, lag=120.0) == play(sh, lag=120.0)


def test_summarize_shares() -> None:
    mk = [b.Result("a", 1, 1, 1, 1, m, 1, 1) for m in (0, 1, 2, 3, 4)]
    s = b.summarize(mk)
    assert s == {"bronze": 0.8, "silver": 0.6, "gold": 0.4, "legend": 0.2}


def test_parse_order_accumulates_deltas() -> None:
    o = b.parse_order(0, [10, 2, 3, 4, 5, [1, 1, 1, 1], 30, 1.0, 4.5, 2, 0, 0], 5.0)
    assert (o.x0, o.y0, o.x1, o.y1, o.d) == (10.0, 15.0, 20.0, 25.0, 30.0)
