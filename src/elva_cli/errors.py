"""Error taxonomy and the exit-code contract.

Exit codes are a public API that pipelines branch on: 0 ok, 1 unexpected, 2 usage,
3 auth, 4 spec failed validation, 5 network/API, 130 interrupted. Never renumber a
shipped code, and never collapse 4 into 1 -- callers rely on the difference
between "your spec is wrong" and "the tool broke".

Every ElvaError carries a stable machine code, a message, and where one exists,
the next action to take."""
