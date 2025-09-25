# Indexing Rewards Eligibility Criteria

This document defines the requirements an Indexer must meet to be eligible for indexing rewards. It includes the current active criteria, a schedule of any upcoming changes, and a log of all historical requirements. The goal is to provide a transparent and predictable set of standards for all network participants.

---

## Upcoming Eligibility Criteria

**We will announce changes to the eligibility criteria in the table below.** Once the change goes live, it will be reflected in the [Active Eligibility Criteria](https://github.com/graphprotocol/service-quality-oracle/blob/main/ELIGIBILITY_CRITERIA.md#active-eligibility-criteria) section of this document.

| Upcoming Requirement | Justification | Date Requirement Will Be Updated/Introduced (YYYY-MM-DD) |
|----------------------|---------------|----------------------------------------------------------|
| **Example Requirement:** | This is a placeholder for future criteria. Watch this space to stay informed. We will also announce upcoming requirements via official channels. | `YYYY-MM-DD` |

> **Note**:
> We will typically allow a 14 day window after announcing a change before it goes live.

---

## Active Eligibility Criteria

The following criteria are used to identify indexers that should be eligible to receive indexing rewards.

- **Days Online Requirement:** Indexers must be active for **5+ days** in a given **28 day** period for rewards eligibility.
- **Daily Query Requirement:** To be active, an indexer must serve at least **1 qualifying query** on **10 different subgraphs**.
- **Query Quality Requirements:** A qualifying query is one that simultaneously meets **all** of the following criteria:
  - Query Response HTTP Status: **200 OK**.
  - Query Response Latency: **< 5,000 ms**.
  - Query Freshness: **< 50,000 blocks** behind chainhead.

Eligibility for indexing rewards is typically refreshed daily via the RewardsEligibilityOracle contract.

> **Note**:
> Once an indexer has successfully qualified for indexing rewards by satisfying the active eligibility criteria, and a corresponding transaction has been submitted on chain by an authorized Oracle into the RewardsEligibilityOracle contract, the now eligible indexer can continue claiming indexing rewards from the protocol for the duration of the qualification period (default is 14 days), even if the active eligibility criteria change.

---

## Eligibility Requirements Changelog

This table tracks changes to the indexing rewards eligibility requirements over time.

| Requirement Category | Requirement Details | Effective Date (YYYY-MM-DD) | Change Type: Initial, Updated, New, Removed | Justification | Notes |
|----------------------|---------------------|-----------------------------|-------------|---------------|-------|
| **Indexer Activity** | Indexers must be active for **5+ days** in a given **28 day** period for indexing rewards eligibility. | TBD | Initial | Encourages indexers to familiarize themselves with infrastructure maintenance and ongoing operations. | Planned for Rewards Eligibility Oracle launch |
| **Query Qualification** | Indexers must serve **≥1 qualifying query** on **≥10 different subgraphs** in a day for the day to count towards the **Indexer Activity** requirement. | TBD | Initial | Encourages indexers to become familiar with the process of syncing a range of subgraphs. | Planned for Rewards Eligibility Oracle launch |
| **Query Response Quality** | *•* Query Response HTTP Status: **200 OK**<br>*•* Query Response Latency: **< 5,000 ms**<br>*•* Query Freshness: **< 50,000 blocks** behind chainhead. | TBD | Initial | *•* Indexer infrastructure needs to serve successful queries to benefit data consumers.<br>*•* Fast query responses are important to data consumers.<br>*•* Encourages indexers to sync to chainhead. | Planned for Rewards Eligibility Oracle launch |

---
