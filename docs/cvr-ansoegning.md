# Applying for CVR system access

Denmark is the last market in this app where a real business register exists and we are not
using it. This file is the application, ready to sign and send. Nothing has been sent and no
account has been created: the application is yours, not the app's.

The adapter is already built and sits switched off in `backend/app/registers.py`. The day the
credentials arrive, put them in two environment variables and Denmark moves from the map to the
register by itself:

```
CVR_USER=<the BrugerId they issue>
CVR_PASSWORD=<the password they issue>
```

## Where it goes

| | |
|---|---|
| Email | **cvrselvbetjening@erst.dk** |
| Post, if you would rather | Erhvervsstyrelsen, Dahlerups Pakhus, Langelinie Allé 17, 2100 København Ø, Denmark |
| Phone, if it stalls | +45 35 29 10 00 |
| Cost | Free. The access is free and so is the application. |
| Turnaround | Count on three weeks. The one published figure I could read is "op til 12 arbejdsdage" on Erhvervsstyrelsen's beneficial-owner guidance, which is the same thing in working days. |

Erhvervsstyrelsen's own guidance for the related REST services asks for the request to come by
**sikker e-mail** (encrypted mail). Ordinary mail will almost certainly be read and answered, but
if your mail client can send encrypted, use it.

## Six things to fill in before you send

1. **Who applies.** The legal entity that will hold the credentials. Two sensible readings and
   it is your call: Think Studio, which operates the server that queries CVR, or Sabertask, which
   is the party actually marketing to the companies. The letter below names both roles separately
   so you can sign as either.
2. **CVR or VAT number of that entity.** Think Studio is Belgian, so that is the KBO/BE number.
   Erhvervsstyrelsen does grant access to foreign entities; they just need the company identified.
3. **A named contact with a direct phone number.** Theirs is a human process, not a form.
4. **The IP addresses the queries will come from.** This matters and it is easy to miss:
   Erhvervsstyrelsen whitelists the addresses you name, and nothing else gets in. For this app
   that is Render's outbound addresses for the `sabertask-live` service, which Render lists in the
   service dashboard under outbound IPs. Give all of them. Add your own office address too if you
   want to be able to test from this machine. **IPv4 only**: their whitelist cannot take IPv6.
5. **Whether the data goes to a third party.** If Think Studio applies and Sabertask's sales floor
   reads the leads, the answer is yes, and it is better said up front than discovered later. It is
   allowed; see the note on §19 stk. 3 below.
6. **A signature.** Print, sign, scan, attach. They have asked for a signed declaration before.

## The letter

Subject: `Ansøgning om system-til-system adgang til CVR (Elasticsearch-distribution)`

> Til Erhvervsstyrelsen, CVR Selvbetjening
>
> Vi ansøger hermed om system-til-system adgang til CVR's distributionsløsning, det vil sige
> Elasticsearch-endpointet `distribution.virk.dk/cvr-permanent/virksomhed/_search`, som beskrevet
> i styrelsens vejledning "Kom godt i gang med Elasticsearch".
>
> **Ansøger**
> Virksomhed: `[navn]`
> CVR- eller momsnummer: `[nummer]`
> Adresse: `[adresse]`
> Kontaktperson: `[navn og stilling]`
> E-mail: `[e-mail]`
> Direkte telefon: `[telefon]`
>
> **Teknisk ansvarlig for systemet** (udfyldes hvis det er en anden end ansøger)
> Virksomhed: `[navn]`
> Kontaktperson, e-mail og telefon: `[...]`
>
> **Formål med adgangen**
> Vi driver et internt salgssystem, der identificerer virksomheder inden for seks brancher som
> potentielle kunder til et software-produkt til styring af udekørende medarbejdere. Systemet
> slår virksomheder op efter branchekode (DB07) og by, og viser navn, adresse, branche,
> antal ansatte og de kontaktoplysninger, virksomheden selv har registreret. Opslagene bruges
> af vores egne sælgere som grundlag for erhvervsrettet kontakt. Data indgår ikke i et produkt,
> der videresælges, og der sker ingen automatisk udsendelse: hver henvendelse skrives og
> afsendes af et menneske.
>
> **Branchekoder vi slår op**
> 811000, 683210, 812100, 812210, 812900, 813000 og 841100.
>
> **Forventet forbrug**
> Opslag sker kun, når en sælger foretager en søgning, typisk nogle få søgninger om dagen.
> Hver søgning er én forespørgsel pr. by med højst 50 resultater. Vi forventer i størrelsesordenen
> 100 forespørgsler om måneden og læser aldrig hele registret ned.
>
> **IP-adresser, der skal whitelistes** (IPv4)
> `[liste]`
>
> **Videregivelse**
> `[Ja/Nej, og til hvem.]`
>
> **Erklæring om reklamebeskyttelse**
> Vi er bekendt med CVR-lovens § 19 og erklærer:
>
> 1. at vi ikke anvender grunddata om reklamebeskyttede enheder med henblik på direkte
>    markedsføring,
> 2. at vi kontrollerer markeringen for reklamebeskyttelse, før en virksomhed kontaktes med et
>    markedsføringsformål, og
> 3. at vi, hvis kontaktoplysninger videregives til tredjemand, tydeligt markerer over for
>    modtageren, at enheden er reklamebeskyttet.
>
> Vores system frasorterer reklamebeskyttede virksomheder helt, inden de vises for en sælger.
>
> Vi beder om at få tilsendt den erklæring, styrelsen ønsker underskrevet, hvis ovenstående ikke
> er tilstrækkelig, samt brugerId og adgangskode til distributionsløsningen.
>
> Med venlig hilsen
> `[navn, stilling, dato, underskrift]`

## What you are signing, in plain words

CVR-loven § 19 lets any Danish company tick a box called **reklamebeskyttelse**. Once it is
ticked, a private company may not use that firm's register data for direct marketing. The flag is
published in the register, so it is on you to check it, not on them to hide. Subsection 3 adds
that if you pass a protected company's contact details to someone else, you have to tell the
recipient clearly that it is protected.

The declaration is a promise about exactly that, which is why the adapter treats it as a hard
filter rather than a preference. A protected company never reaches a lead list, and a company
whose flag cannot be read for any reason is dropped as well. If CVR ever answers without the flag
at all, the Danish search refuses to run and falls back to the map, instead of quietly putting
protected firms in front of a rep.

## One thing I could not verify, and why

The exact wording and title of the declaration Erhvervsstyrelsen wants signed is published on
`datacvr.virk.dk`, and that host sits behind a bot wall that refuses automated readers. I did not
try to get around it. So the declaration above is written from the law it rests on (CVR-loven
§ 19, quoted on Erhvervsstyrelsen's own CVR page) rather than copied from their form, and the
letter asks them to send their form if they want their own wording. That is a normal thing to
ask in a first email and it costs nothing.

Worth knowing while you are in there: Datafordeler's guidance notes that the older webbruger and
tjenestebruger route for CVR's REST services is being phased out at the end of 2026, which is
now. The Elasticsearch distribution endpoint is documented separately and Erhvervsstyrelsen's
guide for it was last updated in November 2025, so it looks unaffected. Ask them to confirm which
route is current, in the same email.
