"""Exercise the USB signing boundary with display, buttons and chip stand-ins.

No device, network or private key is used. This does not replace the RP2040 or board checks.
"""
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
answers, texts, saved = [], [], {}
clock, choice = [0], ["A"]


def ticks():
    clock[0] += 1000
    return clock[0]


time.ticks_ms = ticks
time.ticks_diff = lambda a, b: a - b
time.sleep_ms = lambda ms: None


class Keys:
    def __init__(self, physical=False):
        assert physical
        self.i = 0

    def pressed(self):
        self.i += 1
        return [choice[0]] if self.i % 2 == 0 and choice[0] else []


class Display:
    width = height = 240

    def center_text(self, s, *args):
        texts.append(s)

    text = center_text

    def fill(self, *args):
        pass

    fill_rect = hline = show = fill


sys.modules["lcd"] = types.SimpleNamespace(Keys=Keys, color=lambda *c: c)
sys.modules["wedgie"] = types.SimpleNamespace(send=answers.append)
sys.modules["save"] = types.SimpleNamespace(
    load=lambda k, d=None: saved.get(k, d), store=lambda k, v: saved.__setitem__(k, v))
sys.modules["ui"] = types.SimpleNamespace(
    WHITE="white", INK="ink", MUTED="muted", GREEN_D="green", RED="red", COLS_SMALL=28, COLS_BIG=15,
    progress=lambda *a: None, band=lambda d: None, title=lambda d, s, *a: d.center_text(s),
    buttons=lambda d, *a: None)

import safe as S
import safe_read as R

S.state = "ok"
S.key = {"x": "0x" + "11" * 32, "y": "0x" + "22" * 32}
S.d = Display()
S.sign = lambda digest: (1, 1)  # Public fixture values, not a cryptographic signature.
SAFE = "0x" + "5a" * 20
OTHER = "0x" + "77" * 20
ROLES, MULTI, K_USDC = R.roles_of(SAFE), R.MULTISEND[0], R.K_USDC
LIFI, LIFI_SWAP = R.LIFI, bytes.fromhex("4630a0d8")
w, aw = S.word, S.aword


def send(data=b"", to=OTHER, operation=0):
    answers.clear()
    texts.clear()
    S.on_sign(1, {"chainId": 8453, "safe": SAFE, "to": to, "data": S.hx(data),
                  "operation": operation, "nonce": 3})
    return answers[-1]


def run():
    for key, expected in (("A", "safe_sig"), ("Y", "refused"), (None, "refused")):
        choice[0] = key
        assert send()["type"] == expected
    print("ok: a send needs physical approval; Y and timeout refuse")
    choice[0] = None
    empty = bytes.fromhex("8d80ff0a") + w(32) + w(0)
    assert send(empty, MULTI, 1)["type"] == "error"
    print("ok: an empty batch never signs without approval")
    choice[0] = "A"
    allowance = bytes.fromhex("a8ec43ee") + bytes.fromhex(K_USDC)
    bad = allowance + w(10**12) * 2 + w(10**7) + w(86400) + w(1)
    assert send(bad, ROLES)["type"] == "error"
    print("ok: the daily amount cannot hide a larger initial balance")
    good = allowance + w(10**7) * 3 + w(86400) + w(1)
    assert send(good, ROLES)["type"] == "safe_sig" and "10 USDC" in texts
    print("ok: a supported daily allowance shows its amount and signs on A")
    assign = bytes.fromhex("957ed2b3") + aw(OTHER)
    multiple = assign + w(96) + w(192) + w(2) + w(1) + w(2) + w(2) + w(0) + w(1)
    assert send(multiple, ROLES)["type"] == "error"
    print("ok: a role review cannot hide a second membership change")
    single = assign + w(96) + w(160) + w(1) + w(123) + w(1) + w(1)
    assert send(single, ROLES)["type"] == "safe_sig"
    i = texts.index("role") + 1
    assert "".join(texts[i:i + 3]) == S.hx(w(123))
    print("ok: a single role change displays the full role key")
    for option in (2, 3):
        scope = bytes.fromhex("7508dd98") + w(1) + aw(OTHER) + w(0) + w(160) + w(option)
        assert send(scope, ROLES)["type"] == "error"
    print("ok: delegatecall permissions are not shown as ordinary daily rules")
    # An unrecognized contract call and an incompletely decoded router route must never sign.
    unknown = send(bytes.fromhex("deadbeef") + w(0) + w(0))
    assert unknown["type"] == "error" and "can't review" in unknown["error"]
    action = b"\x00" + S.unhex(OTHER) + w(0) + w(4) + bytes.fromhex("deadbeef")
    nested = bytes.fromhex("8d80ff0a") + w(32) + w(len(action)) + action
    assert send(nested, MULTI, 1)["type"] == "error"
    print("ok: unknown calls refuse both alone and inside a batch")
    data = bytearray(LIFI_SWAP + w(160) + w(0) * 2 + aw(OTHER) + w(0) + bytes(320))
    data[164 + 172:164 + 192] = S.unhex(SAFE)
    data[164 + 224:164 + 256] = w(8453)
    assert send(data, LIFI)["type"] == "error"
    assert send(LIFI_SWAP + w(0) * 3 + aw(SAFE) + w(0), LIFI)["type"] == "error"
    print("ok: a LI.FI receiver alone cannot authorize an unread route")
    S.d.width, S.d.height = 128, 64
    assert send()["type"] == "error"
    print("ok: signing refuses a display that cannot show the review")


if __name__ == "__main__":
    run()
