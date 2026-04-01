# Advisor Playbook

## 1. Session Start
- load memory if available
- detect whether user is new / returning
- if returning, load `show-user` or `status`

## 2. Build Profile
- parse natural-language profile
- if missing critical fields, ask minimal follow-up
- call `onboard` for new user or `quarterly` for full profile refresh

## 3. Explain Recommendation
- show bucket-level recommendation
- show candidate options
- show execution plan
- if active plan exists, show active vs pending difference

## 4. Decision Point
- if user accepts new plan:
  - call `approve-plan`
- if user asks why:
  - explain `decision_card` + `execution_plan_guidance`
- if user postpones:
  - keep active plan or leave pending plan for review

## 5. Execution Feedback
- after user action, call `feedback`
- store executed / skipped / actual_action

## 6. Recurring Reviews
- monthly:
  - refresh account snapshot
  - call `monthly`
- event:
  - call `event`
- quarterly:
  - full profile refresh + `quarterly`

## 7. Policy / News Sidecar
- gather source evidence in OpenClaw
- transform to structured signal
- pass structured signal into kernel
- disclose that signal affected review gate / context, not raw solver math
