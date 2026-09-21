# Security Specification

## Data Invariants
1. A **Deployment** must have a valid `ownerId` matching the creator's UID.
2. A **CostEntry** must reference a valid `deploymentId` and its `ownerId` must match the current user.
3. **ModelRates** are public for reading but should only be editable by admins (or system).
4. **GlobalConfig** is public for reading but only editable by admins.
5. **EnergyTimeSeries** is public for reading (general dashboard) or tied to owner if it's per deployment (though the blueprint says it's legacy history).

## The "Dirty Dozen" Payloads

1. **Identity Spoofing**: Attempt to create a Deployment with `ownerId` set to a different user's UID.
2. **State Shortcutting**: Attempt to update a Deployment status directly to `running` without proper workflow (if we had complex state transitions, but here we just check enum).
3. **Ghost Fields**: Attempt to create a Deployment with an unauthorized field `isAdminDeployment: true`.
4. **ID Poisoning**: Attempt to use a 2KB string as a `deploymentId`.
5. **Unauthorized Read**: Attempt to list `deployments` belonging to another user.
6. **Cross-User Update**: Attempt to update a Deployment owned by another user.
7. **Type Poisoning**: Attempt to set `replicas` to a string `"lots"`.
8. **Invalid Enum**: Attempt to set Deployment `status` to `"exploding"`.
9. **Rate Tampering**: Attempt to update a `ModelRate` as a standard user.
10. **Config Tampering**: Attempt to change `electricityPriceKwh` as a standard user.
11. **Negative Rates**: Attempt to set `inputPricePer1M` to `-100`.
12. **Orphaned Cost Record**: Attempt to create a `CostEntry` for a non-existent `deploymentId`.

## Test Runner (firestore.rules.test.ts placeholder)
(In a real environment I would use the emulator, but here I'll follow the guideline of documenting the plan).
The tests will verify:
- `ownerId` integrity.
- `enum` validation.
- `req.auth.uid` matches `resource.data.ownerId` for read/write on private data.
- Public read access for rates/config.
