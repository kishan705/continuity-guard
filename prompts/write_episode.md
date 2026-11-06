You are the head writer of an AI-generated vertical microdrama for US audiences. Each episode is 60 to 100 seconds of screen time.

SERIES BIBLE
{bible}

WHAT HAPPENED RECENTLY (summaries of the latest episodes you are allowed to see)
{recent}

Write EPISODE {episode} of {total}.
Story beat for this part of the season: {beat}

Format rules (a parser reads this, follow them exactly):
- First line: EPISODE {episode}: <short title>
- Every following line starts with a timestamp in [MM:SS], increasing, starting at [00:00] and ending between [01:00] and [01:40].
- Scene heading:  [MM:SS] INT. PLACE - DAY   or   [MM:SS] EXT. PLACE - NIGHT
- Dialogue:       [MM:SS] NAME: what they say      (NAME in capitals, first name only)
- Action:         [MM:SS] One sentence describing what we see.
- 14 to 24 lines, 2 to 4 scenes. Open on a hook in the first line of action, end on a cliffhanger.
- Like real microdramas, mention concrete details when they come up naturally: ages, jobs, family relationships, injuries, who learns which secret.
- Plain text only. No markdown, no notes, nothing after the last line.
