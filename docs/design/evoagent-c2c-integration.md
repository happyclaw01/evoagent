# EvoAgent: C2C Integration Plan

This document outlines how EvoAgent will integrate with the Claw-to-Claw (C2C) Knowledge Bottle (KB) specification, focusing on EvoAgent as a consumer, and Lobster Distill as the transport and delivery engine. It does not attempt to rewrite or merge the entire C2C protocol, but defines clear touchpoints for cross-framework skill transfer and evaluation within EvoAgent's context.

## 1. Goals & Scope
- Position EvoAgent as a consumer of Knowledge Bottle v2.0; import/export capabilities to support multi-framework portability.
- Treat Lobster Distill as the canonical transfer mechanism for EvoAgent skill bottles.
- Align with C2C high-level concepts without enforcing full protocol adoption in EvoAgent.
- Establish a practical, incremental roadmap that yields demonstrable benefits for EvoAgent users.

## 2. Roles & Boundaries
- C2C Specification (KB v2.0): defines a portable skill descriptor, cross-framework representations, and a future governance layer.
- Lobster Distill: provides encryption, packaging, and human-relay delivery for KBs.
- EvoAgent: consumes KBs via bottle.json, exports internal capabilities to the KB format, and validates cross-framework import paths.

## 3. Knowledge Bottle (KB) in EvoAgent
- Representations: Instruction (OpenClaw-style), Code (Python functions), API (OpenAPI-based) as per bottle.json proposals.
- Export: EvoAgent will implement an exporter that converts internal capabilities to a KB bottle.json payload, plus optional SKILL.md extraction.
- Import: Importers for at least OpenClaw and LangChain to demonstrate cross-framework portability.
- Validation: Basic validator to check bottle.json against the draft schema (v2.0).

## 4. EvoAgent–Lobster Distill integration
- Hook points: bottle export path, password generation, encryption, upload to Lobster Distill, generation of the forward note.
- Import path: end-user in EvoAgent imports a bottle.json and the associated resources, installing skills into evoagent's runtime (with tests).

## 5. Roadmap (high-level)
- Phase 1: KB v2.0 draft mapping to EvoAgent data structures; PoC export for 1-2 skills; OpenClaw and LangChain importers.
- Phase 2: Extend to Dify/Coze; add basic governance signal in the KB metadata.
- Phase 3: Introduce registry-like discovery for cross-framework skills (not full governance yet).

## 6. Risks & Mitigations
- Risk: KB v2.0 complexity across frameworks.
  Mitigation: start with MVP that covers common denominator (instruction + minimal code representation).
- Risk: governance concept adoption across EvoAgent users.
  Mitigation: implement governance as an optional module, not a hard requirement for MVP.

## 7. Deliverables for review
- Draft KB v2.0 schema snippet (JSON example) with sample representations.
- Outline of EvoAgent exporters/importers for OpenClaw and LangChain.
- Updated tests to cover export/import paths.

If you want any adjustments to structure or to emphasize other EvoAgent-specific touchpoints, tell me and I’ll adjust before submitting.
