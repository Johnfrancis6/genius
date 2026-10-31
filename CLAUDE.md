```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
        __start__([<p>__start__</p>]):::first
        transcrire(transcrire)
        urgence(urgence)
        traiter_image(traiter_image)
        route(route)
        clarificateur(clarificateur)
        genius(genius)
        lieux(lieux)
        __end__([<p>__end__</p>]):::last
        __start__ --> transcrire;
        clarificateur -. &nbsp;fin&nbsp; .-> __end__;
        clarificateur -.-> genius;
        clarificateur -.-> lieux;
        route -. &nbsp;fin&nbsp; .-> __end__;
        route -.-> clarificateur;
        route -.-> genius;
        traiter_image --> route;
        transcrire -. &nbsp;fin&nbsp; .-> __end__;
        transcrire -. &nbsp;suite&nbsp; .-> urgence;
        urgence -. &nbsp;fin&nbsp; .-> __end__;
        urgence -. &nbsp;suite&nbsp; .-> traiter_image;
        genius --> __end__;
        lieux --> __end__;
        classDef default fill:#f2f0ff,line-height:1.2
        classDef first fill-opacity:0
        classDef last fill:#bfb6fc
``` 

---

# MANDATORY: Post-Task Documentation (SR-PTD)

**CRITICAL: After completing ANY task that modifies files, you MUST invoke this skill:**

```
Skill tool -> skill: "sr-ptd-skill"
```

**This is NOT optional. Skipping this skill means the task is INCOMPLETE.**

When planning ANY development task, add as the FINAL item in your task list:
```
[ ] Create SR-PTD documentation
```

### Before Starting Any Task:
1. Create your task plan as usual
2. Add SR-PTD documentation as the last task item
3. This step is MANDATORY for: features, bug fixes, refactors, maintenance, research

### When Completing the SR-PTD Task:
1. Read `~/.claude/skills/sr-ptd-skill/SKILL.md` for full instructions
2. Choose template: Full (complex tasks) or Quick (simple tasks)
3. Create file: `SR-PTD_YYYY-MM-DD_[task-id]_[description].md`
4. Save to: `C:/projects/Skills/Dev_doc_for_skills`
5. Fill all applicable sections thoroughly

### Task Completion Criteria:
A task is NOT complete until SR-PTD documentation exists.

### If Conversation Continues After Task:
Update the existing SR-PTD document instead of creating a new one.

---
