---
name: unslop
description: Cut AI tells from writing others read later. Use for PR bodies, commit messages, docs, issues, code comments, and messages sent to people.
disable-model-invocation: false
---

# Unslop

Scan the text for the patterns below, then rewrite it, keeping its meaning and
intended tone. Rule numbers are stable ids that other skills cite; a removed
rule leaves a gap.

## Content

3. **Superficial -ing phrases** ("highlighting", "ensuring", "showcasing"). Delete, or back with a real source.
5. **Vague attributions** ("Experts believe"). Name the source or delete.

## Language

7. **AI vocabulary**: additionally, crucial, delve, enduring, enhance, fostering, garner, interplay, intricate, landscape, pivotal, showcase, tapestry, testament, underscore, vibrant. Use plain words.
8. **Fancy "is"** ("serves as", "stands as", "boasts", "features"). Say "is" or "has".
9. **"Not just X, but Y."** State the point.
10. **Rule of three.** Use the natural number of items.
11. **Synonym cycling.** Pick one name and repeat it.
12. **False ranges** ("from X to Y" off any real scale). List the items.

## Style

13. **Em dashes.** Use none; end the sentence or use a comma. No parentheses, en dashes, or hyphens standing in for them.
14. **Colons as connectors.** Keep colons before a list or an example only.
15. **Boldface** on every proper noun or acronym.
16. **Inline-header lists**, where a bold label and colon restate the line. A bold lead-in ending in a period, followed by new detail, is fine.
17. **Title case headings.** Use sentence case.
18. **Decorative emojis.**
19. **Curly quotes.** Use straight quotes.

## Communication artifacts

20. **Chatbot phrases** ("I hope this helps!", "Let me know if...", "Certainly!").
22. **Sycophancy** ("Great question!"). Respond directly.

## Filler

23. **Filler phrases.** "In order to" is "To"; "due to the fact that" is "because"; "it is important to note that" goes.
24. **Stacked hedges.** One "may" is enough.
25. **Generic conclusions** ("The future looks bright"). State plans or facts.

## Jargon

26. **Abstract metaphor nouns**: substrate, wedge, vector, locus, vantage, nexus, primitive, harness, surface (as in "API surface"), bedrock, scaffolding, modality, paradigm, gold-plating, ratchet, evacuate, endgame, north star, flywheel. Use the concrete word: "base", "add", "way", "more than the job needs", "move out".

## Plain speech

27. **Say what it does, not how it feels.** Name the mechanism or a number: "a column rename fails the build", not "types that follow your schema". A sentence that could appear unchanged in another project's docs says nothing about this one; cut it.
28. **Dense sentences.** One idea per sentence; split one the reader must reparse.
29. **Passive voice.** Name the actor ("the loader parses the file") unless it is unknown or irrelevant.
30. **Adverbs.** Use a stronger verb or the measured number.
31. **Fancy words.** "Use", not "utilize" or "leverage"; "help", not "facilitate"; "many", not "numerous"; "if", not "in the event that".
32. **Mannered prose**: aphorisms, rhetorical fragments, personified code, figurative verbs ("rides along"). Write the literal phrase.
33. **Over-compression**: dropped articles, verbless fragments, arrows, abbreviations. Write whole sentences: "The parser rejects a bad date, exits with code 2, and writes nothing."
