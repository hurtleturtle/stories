# Changelog

## [0.7.0](https://github.com/hurtleturtle/stories/compare/v0.6.0...v0.7.0) (2026-09-30)


### Features

* **converter:** explicit table of contents, author and language ([5c7d7f2](https://github.com/hurtleturtle/stories/commit/5c7d7f264b5c47e4d2bb41b781b7f25e40b93ca2))
* drop MOBI, and offer the valid formats and stylesheets as dropdowns ([b0b1837](https://github.com/hurtleturtle/stories/commit/b0b1837d9d1062d3be2323496f818b9b3f1acdc6))
* **scraper:** cap chapters, scrape time and page size ([6d1f0ec](https://github.com/hurtleturtle/stories/commit/6d1f0ecf36a55def96060cfed19908dd902a8a7d))
* **scraper:** store chapters as they are scraped, resume, catch repeats, sanitise ([93245e8](https://github.com/hurtleturtle/stories/commit/93245e8925df3396dd9fb9c49638f6e1fff929c1))
* **storage:** record artifact paths relative to the artifact folder ([ac7a113](https://github.com/hurtleturtle/stories/commit/ac7a113f66d92205a46d7d094bde50194ef678ed))
* **worker:** cancel running jobs and write the job log in batches ([38ff511](https://github.com/hurtleturtle/stories/commit/38ff5112d4144c50205cfcd50cddf2d78ea2ed44))


### Bug Fixes

* **frontend:** show the API's validation errors instead of "Could not save" ([290d4b0](https://github.com/hurtleturtle/stories/commit/290d4b04d7fc03316b1ba93ed57eb0f9f4031ec4))
* **scraper:** harden next-link handling, filenames, job cancel and URL fetching ([0e8660a](https://github.com/hurtleturtle/stories/commit/0e8660a39a383f2e88f77216535193b838b86061))
* **scraper:** inline assets, retry sensibly, decode correctly, bound Calibre ([89c3556](https://github.com/hurtleturtle/stories/commit/89c355646cc5bcd3518d02e96cd6c400f59fad6c))
* **scraper:** read chapter headings correctly ([c206d3d](https://github.com/hurtleturtle/stories/commit/c206d3dbaae23ab1cd9eca6a29abc714c2fb9e17))
* **worker:** fail jobs whose worker died instead of leaving them running ([ad950a4](https://github.com/hurtleturtle/stories/commit/ad950a45826d140b16688ce8b36c15e6b79eabbc))
* **worker:** stamp heartbeats with the database clock; stale after 2 minutes ([a7ca787](https://github.com/hurtleturtle/stories/commit/a7ca787b0dd59a4763ed766007ddebb9ce1cde4c))

## [0.6.0](https://github.com/hurtleturtle/stories/compare/v0.5.0...v0.6.0) (2026-09-30)


### Features

* **frontend:** give every button an icon alongside its label ([d657e85](https://github.com/hurtleturtle/stories/commit/d657e85a60d040a11308c73fe52e6038b59533a6))
* **frontend:** lilac-tinted secondary buttons, soft red for destructive ones ([ad420ba](https://github.com/hurtleturtle/stories/commit/ad420badc70a8bb086125404d2dc40c11a105112))


### Bug Fixes

* duplicate template names return 409 instead of a server error ([234835d](https://github.com/hurtleturtle/stories/commit/234835d07b5c65fb47d907a0fc6f6b5814f6bf1a))
* **frontend:** fit the job artifacts table on phones ([fb2fa17](https://github.com/hurtleturtle/stories/commit/fb2fa17f98c374f2506abca8950d35bd8e5f8ae0))
* **frontend:** let the phone-size styles actually apply ([f74999d](https://github.com/hurtleturtle/stories/commit/f74999d3243df123a6bf16de0056463240008cfb))
* **frontend:** make artifact downloads work, and tidy the templates pages ([23e4807](https://github.com/hurtleturtle/stories/commit/23e48074457f51fdd6ab01367398f9ca1a65ed25))
* **frontend:** make Log out look like a button ([e9a74c7](https://github.com/hurtleturtle/stories/commit/e9a74c706f039e4a64ea8754a0734ae46c5898c9))
* **frontend:** put the mobile menu's theme switch and Log out under the links ([dda1e61](https://github.com/hurtleturtle/stories/commit/dda1e61afd4b5fd0f461b5f458845b582762228f))

## [0.5.0](https://github.com/hurtleturtle/stories/compare/v0.4.0...v0.5.0) (2026-09-27)


### Features

* **frontend:** add "+ New job" button to the Jobs page header ([be39ef6](https://github.com/hurtleturtle/stories/commit/be39ef6382c4456806d939a6bed732c71f70a4c4))
* **frontend:** Lilac/Dusk light and dark themes, full-screen mobile menu ([35d73cc](https://github.com/hurtleturtle/stories/commit/35d73cc0b07f398343ae1a879d881e8d3894830d))
* **frontend:** plus icon on New job button, fit the jobs table on phones ([2872632](https://github.com/hurtleturtle/stories/commit/28726323dc219e96d788b9ef5e0a0536950b9c75))

## [0.4.0](https://github.com/hurtleturtle/stories/compare/v0.3.0...v0.4.0) (2026-09-27)


### Features

* **frontend:** admin Users page and closed-registration handling ([d8a9634](https://github.com/hurtleturtle/stories/commit/d8a9634ce7cfa728d7587299abb01be29648ae9b))
* user roles, admin user management and a registration switch ([8667f5c](https://github.com/hurtleturtle/stories/commit/8667f5ced0d3996de9f82344aad7ba2b59f41182))


### Bug Fixes

* **frontend:** keep the role dropdown readable on narrow screens ([4d08d8e](https://github.com/hurtleturtle/stories/commit/4d08d8ebe1d3764e2ee14041f8b6e0fde494aa04))

## [0.3.0](https://github.com/hurtleturtle/stories/compare/v0.2.0...v0.3.0) (2026-09-15)


### Features

* resend send-to-kindle email, and actually persist SMTP settings ([d8f9460](https://github.com/hurtleturtle/stories/commit/d8f9460b61545ef2ce6a1d99d024f16622ca5d46))
