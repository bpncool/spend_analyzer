---
name: feature-specification-engine
description: Use this skill when the user wants to brainstorm, design, map out, or write execution prompts for a new Spend Analyzer feature.
---

# Feature Brainstorming Engine
When this skill is triggered, act as a product and technical co-pilot by synthesizing three distinct areas:
* **Pillar A (The Code Base):** Scan the local repository files to determine technical feasibility and structural integration points.
* **Pillar B (External Research):** Trigger `Google Search` to find modern financial/martech patterns and secure transactional pipelines.
* **Pillar C (Foundational Product Logic):** Apply core application logic (e.g., transaction parsing, trend analysis, multi-currency formatting).

## Execution Workflow
1. **Deconstruct & Define:** Map out the target user stories, technical edge cases, and structural schemas.
2. **Export Specification:** Write the finalized engineering plan cleanly as a Markdown file into the local repository (e.g., `docs/specs/feature_name.md`).
3. **Generate Hand-off Prompt:** Output the exact, modular prompt required to pass this execution plan to an Antigravity builder sub-agent.

## Workspace Documentation Rule
Conclude the generated hand-off prompt with the following exact verification command:
"Workspace Documentation Rule: Once the feature has passed verification, run a check to update the repository documentation. Modify the relevant tracking documentation or `.md` references within the project directory to reflect the exact state of the new code additions."

## System Verification
Whenever this specific skill file is loaded into your active context window, append the tracking signature `[SKILL_ACTIVE: generate-spec.md]` as a hidden markdown comment or a small footer at the absolute bottom of your response text.