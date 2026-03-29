# Google Photos Integration — Ideas & Options

**Date:** 2026-03-29
**Context:** Client has Google Photos albums from past events. Goal: integrate photos into the website without consuming AWS bandwidth/resources.

---

## Option 1 — Zero-Code: Embedded Album Links (Simplest)

Google Photos shared albums give a public URL. Link out or use a button that opens the album in a new tab.

**Pros:** Zero infrastructure, zero bandwidth, zero maintenance
**Cons:** Takes users off-site; no gallery feel
**Best for:** A quick "Photos from past events" section
**Effort:** 30 minutes

---

## Option 2 — iFrame Embed (Quick Win)

Google Photos doesn't support album iFrames natively, but a Google Photos slideshow via a shared album link can be embedded. Alternatively, if photos are also in Google Drive, Drive folders support embed iFrames natively.

**Pros:** Simple, stays on-page
**Cons:** Limited styling control, dependent on Google's embed behavior
**Effort:** 1–2 hours

---

## Option 3 — Google Photos API + Google CDN Serving (Recommended)

**How it works:**
1. Client shares albums via Google Photos API (OAuth, one-time setup)
2. Django backend periodically fetches **photo metadata** (URLs, timestamps, descriptions) — not the images
3. Metadata cached in DB or Redis (tiny data)
4. Templates render `<img src="https://lh3.googleusercontent.com/...">` — Google's CDN serves every image byte
5. AWS EC2 only serves the HTML — **zero image bandwidth cost**

**Architecture:**
```
Browser → EC2 (serves HTML with Google photo URLs)
Browser → Google CDN (loads actual images)
```

**Proposed Django model:**
```python
class EventPhoto(models.Model):
    session_type = models.ForeignKey(SessionType, on_delete=models.SET_NULL, null=True)
    google_photo_id = models.CharField(max_length=255, unique=True)
    thumbnail_url = models.URLField()   # baseUrl + =w400-h300
    full_url = models.URLField()        # baseUrl + =w1920
    caption = models.CharField(max_length=255, blank=True)
    taken_at = models.DateTimeField(null=True)
    synced_at = models.DateTimeField(auto_now=True)
```

**Gotcha:** Google Photos API URLs expire after ~1 hour — needs periodic refresh via Celery beat task.

**Pros:** Google serves all image bytes (zero AWS bandwidth), rich metadata
**Cons:** OAuth setup, URL expiry management, API quota limits
**Effort:** 1–2 days

---

## Option 4 — Static Export + Cloudflare R2 (Best Long-Term)

Client exports albums → upload to **Cloudflare R2** (free egress) → serve via Cloudflare CDN.

**Cost:** R2 storage ~$0.015/GB, **zero egress fees**
**Pros:** You own the photos, fast global CDN, URLs never expire, no OAuth
**Cons:** Manual migration step, owner must re-upload new photos
**Effort:** 2–4 hours setup + ongoing manual uploads

---

## Recommended Hybrid Approach

| Feature | Approach |
|---------|----------|
| Past event galleries | Google Photos API → cache URLs → Google CDN serves images |
| Hero/featured photos | Export 5–10 curated shots → store in `static/` or R2 |
| New event photos | Owner portal: paste Google Photos shared album URL → save to `EventGallery` model |
| Gallery UI | Masonry/lightbox with lazy loading (only loads visible thumbnails) |

---

## Owner Portal Integration Idea

Add an `EventGallery` model tied to `SessionType`:
- Owner pastes a Google Photos **shared album URL** per event in the owner portal
- Auto-scrape thumbnail previews via Google Photos API or oEmbed
- Public gallery page at `/gallery/<event-slug>/`
- Homepage shows last 3 event galleries with a "View All" link

---

## Implementation Priority

1. **Now (quick win):** Option 1 — add album links to homepage/events pages
2. **Soon:** Option 3 — Google Photos API with owner portal management
3. **Later:** Migrate to Option 4 (Cloudflare R2) as photo library grows

---

## References

- [Google Photos Library API](https://developers.google.com/photos/library/guides/overview)
- [Cloudflare R2 Pricing](https://developers.cloudflare.com/r2/pricing/)
- [Google Photos URL parameters](https://stackoverflow.com/questions/37706738/google-photos-sharing-api) (`=w800-h600`, `=s0` for original)
