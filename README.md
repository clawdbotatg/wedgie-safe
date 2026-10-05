# Safe signer

A [wedgie](https://wedgie.dev) app: sign [Safe{Wallet}](https://app.safe.global) transactions with a key
that lives in the wedgie's OPTIGA Trust M chip.

- **The key.** First start: press A, and the chip makes a P-256 key in its key slot 2. It never leaves
  the chip. This replaces anything already in that slot. The public key is kept in `/saves/safe/key`.
- **On chain.** The key becomes a Safe owner through Safe's passkey signer
  (`SafeWebAuthnSignerFactory.createSigner(x, y, verifiers)`, safe-modules passkey v0.2.1). Add that
  signer's address as an owner of your Safe. Needs a chain with the P-256 precompile (Base, Optimism,
  Arbitrum, Ethereum).
- **Signing.** The computer sends the transaction's fields. The wedgie works out the Safe tx hash
  itself, shows what the transaction does (to, amount, owner changes, a red line for anything it can't
  read), and signs only when you press A on it. Y, or no answer in 2 minutes, is a no.

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

`hello` also returns `"safe": {"x", "y"}` (null before the key is made).

The Safe signature for this owner is a contract signature (`v = 0`): `r` = the signer contract,
`s` = offset of the dynamic part, which holds `abi.encode(authenticatorData, clientDataFields, r, s)`.

## Saves

- `key`: the public key (x, y). Delete it only if you mean to make a new key: the old one is gone.

MIT
