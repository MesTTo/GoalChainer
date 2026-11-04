; Purpose: the creative controller's dispatch rules, which physixCN gave for its hard gates on omegahive#11
; (comment 6607935015, 3 November 2026), as a lib_deontic theory that step_request.py runs with one step-request's
; clauses as facts. Each norm's label is the rule's name in the controller, so every reason a verdict gives names the
; rule it came from; the labels that are not one of the controller's rules classify what the rules read.
; am[implements a-gc-step-request-1104] am[rests-on c-gc-step-rules-1104]
;
; The facts a step-request gives (step_request.step_facts), each a given:
;   (target pool WHERE) (target pool WHERE CLASS) (target provider WHERE), CLASS own, trusted or open
;   (sends-to WHERE)                    the exact destination, as consent names it
;   (leaf HASH KIND LICENCE)            one per asset that would leave the hive
;   (unreleased HASH) (private HASH PERSON)
;   (cost ESTIMATE BUDGET-LEFT UNIT), and (over-budget ESTIMATE BUDGET-LEFT UNIT) when the estimate is the larger
;   (fact FACT verified REF) (fact FACT unverified REF)
; and (op ...), (generation ...) and (context ...) as they came, which no rule reads.

; --- where work can go -----------------------------------------------------------------------------------------
; The hive's own machines, trusted remote hosts (machines a person enrolled, their own or a partner's under an
; agreement), open remote hosts, and outside models and providers. A pool host the request gives no class is an open
; remote host, the strictest reading of a host nobody said was enrolled.
(normally provider-is-outside (target provider ?w) (destination outside-model))
(normally pool-unclassed-is-open (target pool ?w) (destination open-host))
(normally pool-own (target pool ?w own) (destination own-machine))
(normally pool-trusted (target pool ?w trusted) (destination trusted-host))
(normally pool-open (target pool ?w open) (destination open-host))
(given (trusted own-machine))
(given (trusted trusted-host))
(given (untrusted open-host))
(given (untrusted outside-model))
(given (leaves-hive trusted-host))
(given (leaves-hive open-host))
(given (leaves-hive outside-model))

; --- licences --------------------------------------------------------------------------------------------------
; Licence-open: the hive's own work, CC0, CC-BY, CC-BY-SA, and permissive code licences (MIT, Apache-2.0, BSD), by
; their names and SPDX identifiers. Every other licence, NC and ND ones, unknown and proprietary included, is
; licence-restricted.
(given (open-licence own))
(given (open-licence CC0))
(given (open-licence CC0-1.0))
(given (open-licence CC-BY))
(given (open-licence CC-BY-1.0))
(given (open-licence CC-BY-2.0))
(given (open-licence CC-BY-2.5))
(given (open-licence CC-BY-3.0))
(given (open-licence CC-BY-4.0))
(given (open-licence CC-BY-SA))
(given (open-licence CC-BY-SA-1.0))
(given (open-licence CC-BY-SA-2.0))
(given (open-licence CC-BY-SA-2.5))
(given (open-licence CC-BY-SA-3.0))
(given (open-licence CC-BY-SA-4.0))
(given (open-licence MIT))
(given (open-licence Apache-2.0))
(given (open-licence BSD))
(given (open-licence BSD-2-Clause))
(given (open-licence BSD-3-Clause))
(given (attribution-licence CC-BY))
(given (attribution-licence CC-BY-1.0))
(given (attribution-licence CC-BY-2.0))
(given (attribution-licence CC-BY-2.5))
(given (attribution-licence CC-BY-3.0))
(given (attribution-licence CC-BY-4.0))
(given (attribution-licence CC-BY-SA))
(given (attribution-licence CC-BY-SA-1.0))
(given (attribution-licence CC-BY-SA-2.0))
(given (attribution-licence CC-BY-SA-2.5))
(given (attribution-licence CC-BY-SA-3.0))
(given (attribution-licence CC-BY-SA-4.0))
(normally licence-unlisted (leaf ?h ?k ?l) (restricted ?h))
(normally licence-listed (and (leaf ?h ?k ?l) (open-licence ?l)) (not (restricted ?h)))
(prefer licence-listed licence-unlisted)

; --- rule 1: what may leave the hive, and to where -------------------------------------------------------------
; licence-open: an open asset may go to any destination, and its attribution travels with CC-BY and CC-BY-SA.
(normally licence-open (and (leaf ?h ?k ?l) (open-licence ?l) (destination ?d)) (may (send ?h ?d)))
(normally attribution-travels (and (leaf ?h ?k ?l) (attribution-licence ?l)) (attribution ?h ?l))
; licence-restricted: a restricted asset never goes to an outside model or provider, or an open remote host, and may
; go only to the hive's own machines or trusted remote hosts.
(normally licence-restricted (and (restricted ?h) (destination ?d) (untrusted ?d)) (forbidden (send ?h ?d)))
(normally licence-restricted-trusted (and (restricted ?h) (destination ?d) (trusted ?d)) (may (send ?h ?d)))
; private-needs-consent: a person's private material leaves their hive only with their consent for the exact
; destination, shown on the card, which the controller reports as a verified fact (consent PERSON HASH WHERE).
(normally private-needs-consent (and (private ?h ?p) (sends-to ?w) (destination ?d) (leaves-hive ?d))
  (must (consent ?p ?h ?w)))
(except consent-given (fact (consent ?p ?h ?w) verified ?r) (not (must (consent ?p ?h ?w))))
(normally consent-shown
  (and (private ?h ?p) (sends-to ?w) (destination ?d) (leaves-hive ?d) (fact (consent ?p ?h ?w) verified ?r))
  (consented ?p ?h ?w))
; unreleased-trusted-only: unreleased work goes only to the hive's own machines or trusted remote hosts, whatever
; its licence.
(normally unreleased-trusted-only (and (unreleased ?h) (destination ?d) (untrusted ?d)) (forbidden (send ?h ?d)))
; When rules conflict, the strictest one applies: every prohibition out-ranks every permission.
(prefer licence-restricted licence-open)
(prefer licence-restricted licence-restricted-trusted)
(prefer unreleased-trusted-only licence-open)
(prefer unreleased-trusted-only licence-restricted-trusted)

; --- rule 2: budget-over-left ----------------------------------------------------------------------------------
; A step whose estimated cost is over the budget left is forbidden for automatic dispatch: the person who pays
; approves it or changes the budget, which is never raised automatically.
(normally budget-over-left (over-budget ?e ?l ?u) (forbidden (auto-dispatch ?e ?l ?u)))

; --- what the step rests on ------------------------------------------------------------------------------------
; A fact the step rests on that isn't verified yet is to be verified first, the incident domain's verification goal.
(normally verify-first (fact ?f unverified ?r) (must (verify ?f)))
