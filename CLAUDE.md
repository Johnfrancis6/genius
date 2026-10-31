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