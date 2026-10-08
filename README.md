# Safe signer

A [wedgie](https://wedgie.dev) app: sign [Safe{Wallet}](https://app.safe.global) transactions with a key
that lives in the wedgie's OPTIGA Trust M chip.

- **The key.** First start: press A, and the chip makes a P-256 key in its key slot 2. It never leaves
  the chip. This replaces anything already in that slot. The public key is kept in `/saves/safe/key`.
- **On chain.** The key becomes a Safe owner through Safe's passkey signer
  (`SafeWebAuthnSignerFactory.createSigner(x, y, verifiers)`, safe-modules passkey v0.2.1). That signer's
  address is the wedgie's Safe owner address, the same on every chain: the home screen shows it
  (`safe_addr.py` works it out, once per key), and [wedgie.dev/safe](https://wedgie.dev/safe) shows the
  same one. Needs a chain with the P-256 precompile (Base, Optimism, Arbitrum, Ethereum).
- **wedgie.dev/safe** makes a new Safe with the wedgie as an owner, adds it to a Safe you already own
  (from a browser wallet that is an owner), and signs and executes transactions.
- **Signing.** The computer sends the transaction's fields. The wedgie works out the Safe tx hash
  itself, shows what the transaction does (to, amount, owner changes, a red line for anything it can't
  read), and signs only when you press A on it. Y, or no answer in 2 minutes, is a no.
  Amounts are big; every address is shown in full with its blockie beside it (the same 8x8 pattern
  wallets draw, `safe_blockie.py`; colors are the nearest of the wedgie's 16). The first page shows a
  blockie of the Safe tx hash: Instant Wallet's phone draws the same one, so a send started on the phone
  and finished on a computer can be checked for a swap. Instant Wallet's settings read in plain words
  (daily limit, fee cap, the USDC fee rule, "the Instant relay"); a rule it can't read is red.

## Controls

- A: make the key (first start) / sign
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

`hello` also returns `"safe": {"x", "y"}` (null before the key is made), `"signer"` (its Safe owner
address, as the home screen shows it) and `"safe_chunk": 4000`.

The wedgie keeps a list of its Safes (save `safes`, at most 32, newest first) so any computer can list
them. Signing for a Safe adds it; a host that made or opened one adds it with `safe_note`:

```
{"id":5,"type":"safe_list"}                                   -> {"id":5,"type":"safe_list","safes":["8453:0x..", ...]}
{"id":6,"type":"safe_note","chainId":8453,"safe":"0x.."}      -> {"id":6,"type":"ok","safes":3}
```

It's only a list of addresses: wedgie.dev/safe checks on chain that the wedgie is an owner before showing one.

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
names this Safe). Anything else is a red line with its selector and address.

The Safe signature for this owner is a contract signature (`v = 0`): `r` = the signer contract,
`s` = offset of the dynamic part, which holds `abi.encode(authenticatorData, clientDataFields, r, s)`.

## Saves

- `key`: the public key (x, y). Delete it only if you mean to make a new key: the old one is gone.
- `signer`: the Safe owner address worked out from `key` (made again if it's missing).
- `safes`: the Safes it's in (`"<chainId>:<address>"`), for wedgie.dev/safe's list. Making a new key clears it.

MIT
