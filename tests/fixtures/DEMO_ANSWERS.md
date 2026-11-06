# Demo show: what the checker should find

Made-up show used for tests and the "Load demo show" button. Not Kuku content.

| Episode 3 line | Type | Contradicts | Who should catch it |
| --- | --- | --- | --- |
| 00:08 `ROSE: Get out of my house, Victor.` | status | Ep 2, 00:40: the doctor covers Rose's face (she died) | rules (offline baseline too) |
| 00:20 `MAYA: I'm 29, Ethan.` | identity | Ep 1, 00:02: "Maya Chen, 26" | rules (offline baseline too) |
| 00:31 `DAVID: I know that Maya is Ethan's wife.` | knowledge | Only Victor learned this (ep 2, 00:50); David never did | rules (offline baseline too) |
| 00:38 `Lily lifts a box of books with both arms` | physical | Ep 2, 00:16: her left arm is in a cast | AI judge only (the regex baseline misses it) |

Should NOT be flagged:

- Ep 2, 01:05 `You're... the CEO?` and ep 3, 00:25 Ethan admitting he lied: the courier-to-CEO reveal is an intended twist (development).
- Ep 3, 00:43 `My sister Lily`: consistent with ep 1.
