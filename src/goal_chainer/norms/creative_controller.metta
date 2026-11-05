; Purpose: the creative controller's dispatch rules, which physixCN gave for its hard gates on omegahive#11
; (comment 6607935015, 3 November 2026) and refined in their answers (comment 6628012601, 4 November, and comment
; 6653935601, 5 November), as a lib_deontic theory that step_request.py runs with one step-request's clauses as facts.
; Each norm's label is the rule's name in the controller, so every reason a verdict gives names the rule it came from;
; the labels that are not one of the controller's rules classify what the rules read.
; am[implements a-gc-step-request-1104] am[rests-on c-gc-step-rules-1104] am[rests-on c-gc-physix-answers-1104]
; am[implements a-gc-lic-norms-1105] am[rests-on c-gc-physix-licence-1105]
;
; The facts a step-request gives (step_request.step_facts), each a given:
;   (target pool WHERE) (target pool WHERE CLASS) (target provider WHERE), CLASS own, trusted or open, any other
;                                       class given as open
;   (sends-to WHERE)                    the exact destination, as consent names it
;   (leaf HASH KIND LICENCE)            one per asset that would leave the hive
;   (source HASH KIND LICENCE)          one per asset leaves were made from that doesn't leave
;   (unreleased HASH) (private HASH PERSON) (from HASH ORIGIN), of leaves and sources alike
;   (cost ESTIMATE BUDGET-LEFT UNIT), and (over-budget ESTIMATE BUDGET-LEFT UNIT) when the estimate is the larger
;   (fact FACT verified REF) (fact FACT unverified REF), a revoked or expired fact never given; a relicence is the
;                                       fact (relicence HASH LICENCE PERSON TIME) of an own asset the request describes
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
; A licence is read by its SPDX identifier, own being the hive's or the person's own material, and a plain Creative
; Commons name is an alias of its current SPDX version, so CC-BY reads as CC-BY-4.0. Licence-open: own, CC0, CC-BY,
; CC-BY-SA and the permissive code licences MIT, Apache-2.0 and BSD-2-Clause or BSD-3-Clause, by their SPDX ids. Every
; other licence, NC and ND ones, missing, unknown, proprietary and any name SPDX doesn't list, plain BSD among them,
; is licence-restricted. Leaves and sources are assets alike: what a leaf was made from has a licence too.
(normally leaf-is-asset (leaf ?h ?k ?l) (asset ?h ?k ?l))
(normally source-is-asset (source ?h ?k ?l) (asset ?h ?k ?l))
(given (licence-alias CC0 CC0-1.0))
(given (licence-alias CC-BY CC-BY-4.0))
(given (licence-alias CC-BY-SA CC-BY-SA-4.0))
(given (licence-alias CC-BY-NC CC-BY-NC-4.0))
(given (licence-alias CC-BY-ND CC-BY-ND-4.0))
(given (licence-alias CC-BY-NC-SA CC-BY-NC-SA-4.0))
(given (licence-alias CC-BY-NC-ND CC-BY-NC-ND-4.0))
(normally licence-as-stated (asset ?h ?k ?l) (licence ?h ?l))
(normally licence-as-alias (and (asset ?h ?k ?a) (licence-alias ?a ?l)) (licence ?h ?l))
; Nothing relicenses an asset but an explicit step a person approved, which the controller reports as the verified
; fact (relicence HASH LICENCE PERSON TIME), who approved it and when; only an own asset is its owner's to relicense,
; and it keeps its from links, so what it came from still binds it (physixCN's answer of 5 November).
(normally licence-relicensed (and (asset ?h ?k own) (fact (relicence ?h ?l ?p ?t) verified ?r)) (licence ?h ?l))
(normally licence-relicensed-alias
  (and (asset ?h ?k own) (fact (relicence ?h ?a ?p ?t) verified ?r) (licence-alias ?a ?l)) (licence ?h ?l))
(except relicence-replaces-own (and (asset ?h ?k own) (fact (relicence ?h ?l ?p ?t) verified ?r)) (not (licence ?h own)))
(given (open-licence own))
(given (open-licence CC0-1.0))
(given (open-licence CC-BY-1.0))
(given (open-licence CC-BY-2.0))
(given (open-licence CC-BY-2.5))
(given (open-licence CC-BY-3.0))
(given (open-licence CC-BY-4.0))
(given (open-licence CC-BY-SA-1.0))
(given (open-licence CC-BY-SA-2.0))
(given (open-licence CC-BY-SA-2.5))
(given (open-licence CC-BY-SA-3.0))
(given (open-licence CC-BY-SA-4.0))
(given (open-licence MIT))
(given (open-licence Apache-2.0))
(given (open-licence BSD-2-Clause))
(given (open-licence BSD-3-Clause))
(given (attribution-licence CC-BY-1.0))
(given (attribution-licence CC-BY-2.0))
(given (attribution-licence CC-BY-2.5))
(given (attribution-licence CC-BY-3.0))
(given (attribution-licence CC-BY-4.0))
(given (attribution-licence CC-BY-SA-1.0))
(given (attribution-licence CC-BY-SA-2.0))
(given (attribution-licence CC-BY-SA-2.5))
(given (attribution-licence CC-BY-SA-3.0))
(given (attribution-licence CC-BY-SA-4.0))
(normally licence-unlisted (asset ?h ?k ?l) (restricted ?h))
(normally licence-listed (and (licence ?h ?l) (open-licence ?l)) (not (restricted ?h)))
(prefer licence-listed licence-unlisted)
; Share-alike licences come in families whose members combine: CC BY-SA 2.0 and later let an adaptation take a later
; version, so 2.0 to 4.0 combine under 4.0, while 1.0 binds an adaptation to itself alone; the NC-SA versions alike.
(given (share-alike-family CC-BY-SA-1.0 cc-by-sa-1))
(given (share-alike-family CC-BY-SA-2.0 cc-by-sa))
(given (share-alike-family CC-BY-SA-2.5 cc-by-sa))
(given (share-alike-family CC-BY-SA-3.0 cc-by-sa))
(given (share-alike-family CC-BY-SA-4.0 cc-by-sa))
(given (share-alike-family CC-BY-NC-SA-1.0 cc-by-nc-sa-1))
(given (share-alike-family CC-BY-NC-SA-2.0 cc-by-nc-sa))
(given (share-alike-family CC-BY-NC-SA-2.5 cc-by-nc-sa))
(given (share-alike-family CC-BY-NC-SA-3.0 cc-by-nc-sa))
(given (share-alike-family CC-BY-NC-SA-4.0 cc-by-nc-sa))
(given (families-clash cc-by-sa-1 cc-by-sa))
(given (families-clash cc-by-sa-1 cc-by-nc-sa-1))
(given (families-clash cc-by-sa-1 cc-by-nc-sa))
(given (families-clash cc-by-sa cc-by-sa-1))
(given (families-clash cc-by-sa cc-by-nc-sa-1))
(given (families-clash cc-by-sa cc-by-nc-sa))
(given (families-clash cc-by-nc-sa-1 cc-by-sa-1))
(given (families-clash cc-by-nc-sa-1 cc-by-sa))
(given (families-clash cc-by-nc-sa-1 cc-by-nc-sa))
(given (families-clash cc-by-nc-sa cc-by-sa-1))
(given (families-clash cc-by-nc-sa cc-by-sa))
(given (families-clash cc-by-nc-sa cc-by-nc-sa-1))
(normally share-alike-licence (and (licence ?h ?l) (share-alike-family ?l ?f)) (share-alike-of ?h ?f))

; --- what a derived asset carries ------------------------------------------------------------------------------
; Anything made from another asset inherits the strictest of everything it came from, through every step back:
; private to every owner a source has, unreleased when any source is (physixCN's answer of 4 November), and every
; restriction of any source's licence, its share-alike family and the credit its attribution licence asks, own never
; loosening any of them (their answer of 5 November). Licences that can't be combined, two share-alike families, read
; as restricted rather than picking one; an ND source is restricted already, and so is all it is made into.
(normally inherits-private (and (from ?h ?s) (private ?s ?p)) (private ?h ?p))
(normally inherits-unreleased (and (from ?h ?s) (unreleased ?s)) (unreleased ?h))
(normally inherits-restricted (and (from ?h ?s) (restricted ?s)) (restricted ?h))
(prefer inherits-restricted licence-listed)
(normally inherits-share-alike (and (from ?h ?s) (share-alike-of ?s ?f)) (share-alike-of ?h ?f))
(normally share-alike-clash (and (share-alike-of ?h ?f) (share-alike-of ?h ?g) (families-clash ?f ?g)) (restricted ?h))
(prefer share-alike-clash licence-listed)
(normally owes-own-credit (and (from ?h ?s) (licence ?s ?l) (attribution-licence ?l)) (owes-credit ?h ?s ?l))
(normally owes-inherited-credit (and (from ?h ?s) (owes-credit ?s ?o ?l)) (owes-credit ?h ?o ?l))

; --- rule 1: what may leave the hive, and to where -------------------------------------------------------------
; Only leaves leave: a source stays home, so no rule sends one. licence-open: an open leaf may go to any destination,
; and its attribution travels with CC-BY and CC-BY-SA, as does the credit each source it came from asks and the
; share-alike family it must be shared under.
(normally licence-open (and (leaf ?h ?k ?x) (licence ?h ?l) (open-licence ?l) (not (restricted ?h)) (destination ?d))
  (may (send ?h ?d)))
(normally attribution-travels (and (leaf ?h ?k ?x) (licence ?h ?l) (attribution-licence ?l)) (attribution ?h ?l))
(normally source-credit-travels (and (leaf ?h ?k ?x) (owes-credit ?h ?s ?l)) (attribution-from ?h ?s ?l))
(normally share-alike-travels (and (leaf ?h ?k ?x) (share-alike-of ?h ?f)) (share-alike ?h ?f))
; licence-restricted: a restricted asset never goes to an outside model or provider, or an open remote host, and may
; go only to the hive's own machines or trusted remote hosts.
(normally licence-restricted (and (leaf ?h ?k ?x) (restricted ?h) (destination ?d) (untrusted ?d))
  (forbidden (send ?h ?d)))
(normally licence-restricted-trusted (and (leaf ?h ?k ?x) (restricted ?h) (destination ?d) (trusted ?d))
  (may (send ?h ?d)))
; private-needs-consent: a person's private material leaves their hive only with their consent for the exact
; destination, shown on the card, which the controller reports as a verified fact (consent PERSON HASH WHERE). A
; source stays home, so only a leaf needs it.
(normally private-needs-consent (and (leaf ?h ?k ?l) (private ?h ?p) (sends-to ?w) (destination ?d) (leaves-hive ?d))
  (must (consent ?p ?h ?w)))
(except consent-given (fact (consent ?p ?h ?w) verified ?r) (not (must (consent ?p ?h ?w))))
(normally consent-shown
  (and (leaf ?h ?k ?l) (private ?h ?p) (sends-to ?w) (destination ?d) (leaves-hive ?d)
       (fact (consent ?p ?h ?w) verified ?r))
  (consented ?p ?h ?w))
; unreleased-trusted-only: unreleased work goes only to the hive's own machines or trusted remote hosts, whatever
; its licence.
(normally unreleased-trusted-only (and (leaf ?h ?k ?l) (unreleased ?h) (destination ?d) (untrusted ?d))
  (forbidden (send ?h ?d)))
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
