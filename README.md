# Safe Signer

A [wedgie](https://wedgie.dev) app: sign [Safe{Wallet}](https://app.safe.global) transactions with a key
that lives in the wedgie's secure chip: an ATECC608 or an OPTIGA Trust M.

- **The key: yours, made once, locked for good.** First start: press A, and the chip makes a P-256 key.
  It never leaves the chip.
  - **Trust M** (`safe_key.py`): the key goes in slot KEY2 (replacing an unlocked one) and its public key
    in DATA[11], then both are locked (lifecycle operational). After that nothing can replace the key,
    change its public key or unlock them: no app, no computer, no one. Every start reads the public key
    from the chip and checks it with a fresh signature; the Pico keeps nothing that matters. A chip whose
    KEY2 is already locked with a key that isn't Safe Signer's shows **Swap the chip** and never signs.
    A key from safe-12 or older (unlocked, its public key only in the save) asks **Lock this key?** once:
    yes keeps it for good, no makes your own. Other apps use KEY3 and KEY4.
  - **ATECC608** (slot 0): A writes and locks its config (`atecc.CONFIG`) and locks its data zone if that
    isn't done yet, makes the key in slot 0, then locks slot 0. After that nothing can replace the key; the
    chip works its public key out every start. Other slots stay free for other apps. A chip whose config
    sets slot 0 up some other way shows **Swap the chip**. A safe-12 key (unlocked, saved) asks
    **Lock this key?** the same way.
- **On chain.** The key becomes a Safe owner through Safe's passkey signer
  (`SafeWebAuthnSignerFactory.createSigner(x, y, verifiers)`, safe-modules passkey v0.2.1). That signer's
  address is the wedgie's Safe owner address, the same on every chain: the home screen shows it
  (`safe_addr.py` works it out, once per key), and [wedgie.dev/safe](https://wedgie.dev/safe) shows the
  same one. Needs a chain with the P-256 precompile (Base, Optimism, Arbitrum, Ethereum).
- **wedgie.dev/safe** makes a new Safe with the wedgie as an owner, adds it to a Safe you already own
  (from a browser wallet that is an owner), and signs and executes transactions.
- **Prove it's you** (`safe_msg.py`): a site sends a short text and a code; the wedgie shows the text and, on A,
  its key signs both, and the chip's factory key signs the key (Infineon's certificate), so the site knows it's
  this wedgie, just now. [wedgie.dev/telegram](https://wedgie.dev/telegram) lets you into the wedgie Telegram group with it.
- **Execute on wedgie.dev/safe, not Safe{Wallet}.** Safe{Wallet} can't execute a transaction a wedgie
  signed: it fails with GS021 ([Safe's bug](https://github.com/safe-global/safe-wallet-monorepo/issues/8808)).
  Signing there is fine.
- **Signing.** The computer sends the transaction's fields. The wedgie works out the Safe tx hash
  itself, shows what the transaction does (to, amount, owner changes, a red line for anything it can't
  read), and signs only when you press A on it. Y, or no answer in 2 minutes, is a no.
  Amounts are big; every address is shown in full with its blockie beside it (the same 8x8 pattern
  wallets draw, `safe_blockie.py`; colors are the nearest of the wedgie's 16). The first page shows a
  blockie of the Safe tx hash: Instant Wallet's phone draws the same one, so a send started on the phone
  and finished on a computer can be checked for a swap. Every page is a few plain words, and every Instant Wallet action is one page: a send, an owner change,
  a limit change, a swap (its exact approval folds in). The relay's fee (up to 1 USDC or 0.001 ETH) is a
  small line on that page; a bigger one keeps its own page. First-time limit setup is two pages: the
  amounts, then which key may spend them. Anything it can't read is red. The reading code (`safe_read.py`) loads only while a
  question is up.
  Every page shows which Safe at the top, as wedgie.dev/safe does: a dark card with its blockie and address (first 6 and last 4 in white); the chain is at the bottom.
- **What it won't take on trust.** A DELEGATECALL to anything but Safe's MultiSend is one red page, "can
  take all", and nothing else about it. "Daily limit" pages only for this Safe's own Roles (its CREATE2
  address, worked out on the wedgie); any other contract with the same calls is "Unknown". An unlimited
  approval says "ALL USDC", red. A LI.FI swap or bridge shows who gets paid (green only when it's this
  Safe), then "trust LI.FI" in big red: it can't check what comes back. A page with a big red line has a
  red title. What it can't read it says in red, and A still signs (only a DELEGATECALL
  and a gas refund are refused: the screen can't show them). A
  button press made before a page is up doesn't answer it.

## Controls

- A: make the key (first start) / lock a key from before / sign
- Y: no

## USB

One JSON line each way. Anything else goes to the wedgie firmware as usual.

```
{"id":1,"type":"safe_sign","tx":{"chainId":8453,"safe":"0x..","to":"0x..","value":"0","data":"0x",
 "operation":0,"safeTxGas":0,"baseGas":0,"gasPrice":0,"gasToken":"0x0..","refundReceiver":"0x0..","nonce":0}}
-> {"id":1,"type":"safe_sig","safeTxHash":"0x..","x":"0x..","y":"0x..","r":"0x..","s":"0x..",
    "authenticatorData":"0x..","clientDataFields":"\"origin\":\"https://wedgie.dev\""}
-> {"id":1,"type":"refused"}
```

`hello` also returns `"safe": {"x", "y", "chip"}` (null until there's a key it signs with), `"signer"` (its Safe
owner address, as the home screen shows it), `"safe_state"` (`"ok"`, `"none"` no key yet, `"lock"` a key from
before waiting for its lock, `"swap"` a chip locked with someone else's key) and `"safe_chunk": 4000`.

The wedgie keeps a list of its Safes (save `safes`, at most 32, newest first) so any computer can list
them. Signing for a Safe adds it; a host that made or opened one adds it with `safe_note`:

```
{"id":5,"type":"safe_list"}                                   -> {"id":5,"type":"safe_list","safes":["8453:0x..", ...]}
{"id":6,"type":"safe_note","chainId":8453,"safe":"0x.."}      -> {"id":6,"type":"ok","safes":3}
```

It's only a list of addresses: wedgie.dev/safe checks on chain that the wedgie is an owner before showing one.

To take a queued transaction off the list (no transaction on chain), the wedgie signs Safe's `DeleteRequest`
for it. The host sends the fields with `dataHash` instead of `data`; the wedgie works out the Safe tx hash, shows
**Remove it? #n** (it can still run till another transaction takes #n), and signs on A:

```
{"id":7,"type":"safe_remove","tx":{..., "dataHash":"0x..", "nonce":15},"totp":497960}
-> {"id":7,"type":"safe_sig","safeTxHash":"0x..","deleteHash":"0x..", ...the same signature fields}
```

A site's text message (`personal_sign`, "Sign in with Ethereum") signed for a Safe (ERC-1271, as Safe's fallback
handler checks it). The host sends the message's own bytes; the wedgie shows every line of the text, works out the
EIP-191 hash and Safe's `SafeMessage` hash itself, and signs on A. Plain ASCII text only, up to 1500 bytes: anything
else it can't show, so it won't sign (`safe_msg.py`, loaded only for it):

```
{"id":8,"type":"safe_message","chainId":1,"safe":"0x..","hex":"0x<the message's bytes>"}
-> {"id":8,"type":"safe_sig","messageHash":"0x..","safeMessageHash":"0x..", ...the same signature fields}
```

Safe's Transaction Service only deletes for the wallet that proposed it, so wedgie.dev/safe sends this to
Instant Wallet's queue, which checks it through the signer contract (`isValidSignature`) and lists it as removed.

A USB line is at most 6 KB. A bigger transaction (a bridge swap's calldata) sends its data ahead in
pieces of up to `safe_chunk` hex characters, then `safe_sign` with `"data": "@"`:

```
{"id":2,"type":"safe_data","at":0,"hex":"8d80ff0a..."}     -> {"id":2,"type":"safe_data","have":2000}
{"id":3,"type":"safe_data","at":2000,"hex":"..."}          -> {"id":3,"type":"safe_data","have":3900}
{"id":4,"type":"safe_sign","tx":{..., "data":"@"}}
```

`at` = bytes sent so far (0 starts over). At most 8000 bytes of data (more answers `too big`: joining
the pieces needs one block that size, and a used RP2040 heap doesn't always have a bigger one). The wedgie hashes what it was given, so the host still checks
the `safeTxHash` it gets back.

What it reads in plain words: ETH and token sends, owner and threshold changes, modules on and off, the
7-day recovery module (Candide: guardians, cancel), Instant Wallet's daily budget (Zodiac Roles), exact
approvals, and swaps through Uniswap (pay, minimum back, who gets paid) or LI.FI (whether the calldata
names this Safe; not what comes back, so its page is red). Anything else is a red line with its selector and address.

## Clear signing (ERC-7730)

Every other contract call is read from the public [ERC-7730 registry](https://github.com/ethereum/clear-signing-erc7730-registry)'s
descriptors, sent in the [wire format](https://github.com/ZKNoxHQ/eth-universal-signer/blob/7730-wire-format-implementations/specs/7730_wire_format.md)
(Bacca's CBOR binding, v 29.09.26-1). The page shows the descriptor's intent as the title, then its fields: amounts
with the token's ticker, every address in full with its blockie ("this Safe" when it is), dates, enums, a call
inside a call (one level).

- **Nothing to trust in the host.** wedgie.dev/safe sends the descriptors and tokens a tx needs ahead of it
  (`safe_clear`). Each one carries a Merkle proof (signature algorithm 4) to a root built into this app
  (`safe_roots.py`, made by wedgie-dev `wire/release.py`), and the app is signed when wedgie.dev publishes it. A
  host can leave something out (the page then says it can't read the call), never change it.
- **Two roots.** a: descriptors an auditor attested (ERC-8176; today Cyfrin) and the tokens. b: the rest of the
  registry; their pages end in red "not audited".
- **New registry data needs a new app.** The roots change with each release of the data.
- **Refused, not half shown:** a `mustMatch` field that doesn't match, an enum value the descriptor doesn't
  list, anything it can't decode. Then it's the red "can't read this" page, with the reason.
- `safe_7730.py` and `safe_wire.py` (a copy of wedgie-dev `wire/wire.py`) load only while a question with a
  bundle is up. Tested against the registry's own test transactions (wedgie-dev `tools/test_clear.py`).

```
{"id":7,"type":"safe_clear","at":0,"hex":"a20881..."}      -> {"id":7,"type":"safe_clear","have":1201}
{"id":8,"type":"safe_sign","tx":{...}}                     (uses the bundle, then drops it)
```

The bundle is a CBOR map `{8: [token-information], 13: [transaction-info]}` (eth-sign-request's keys), at most
6000 bytes, in pieces of up to `safe_chunk` hex characters like `safe_data`. `hello` says which data the app
trusts: `"safe_clear": "<tag>"`, the folder wedgie.dev/clear/<tag>/.

The Safe signature for this owner is a contract signature (`v = 0`): `r` = the signer contract,
`s` = offset of the dynamic part, which holds `abi.encode(authenticatorData, clientDataFields, r, s)`.

## Saves

- `key`: only a safe-12 key's public key (x, y), to offer to lock it; dropped once it's locked or replaced.
  The chip keeps the key and its public key.
- `signer`: the Safe owner address worked out from `key` (made again if it's missing).
- `safes`: the Safes it's in (`"<chainId>:<address>"`), for wedgie.dev/safe's list. Making a new key clears it.

MIT
