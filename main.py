# Ưu tiên chọn stream .m3u8 hoặc .flv hợp lệ
        if not entry.get("user_agent"):
            entry["user_agent"] = UA
            
        # Kiểm tra xem có phải link stream trực tiếp hợp lệ không
        if is_direct_stream_url(entry["url"], entry.get("content_type", "")):
            streams.append(entry)

    # Sắp xếp các luồng tìm được (ưu tiên m3u8)
    streams.sort(key=lambda x: (0 if ".m3u8" in x["url"].lower() else 1, len(x["url"])))
    match["streams"] = streams
    match["stream_urls"] = [s["url"] for s in streams]

    if streams:
        print(f"   ✅ Thành công: Tìm thấy {len(streams)} luồng cho {match_name[:50]}")
    else:
        print(f"   ⚠️ Không tìm thấy luồng trực tiếp nào cho {match_name[:50]}")

    return match


async def crawl_homepage(context: BrowserContext) -> list[dict[str, Any]]:
    print(f"🌐 Đang truy cập trang chủ: {TARGET_URL}")
    page = await context.new_page()
    await install_route_filter(page, homepage=True)

    matches: list[dict[str, Any]] = []
    try:
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(HOME_WAIT_MS)

        # Lưu debug trang chủ nếu cần
        try:
            content = await page.content()
            Path(OUTPUT_HOME_DEBUG_HTML).write_text(content, encoding="utf-8")
            await page.screenshot(path=OUTPUT_HOME_DEBUG_PNG, full_page=True)
        except Exception:
            pass

        # Trích xuất danh sách trận đấu từ trang chủ
        matches = await page.evaluate(
            r"""() => {
                const clean = (v) => String(v || "").replace(/\s+/g, " ").trim();
                const out = [];
                const seenUrls = new Set();

                // Quét các thẻ card trận đấu phổ biến
                const cards = document.querySelectorAll(
                    "a[href*='/live/'], a[href*='/match/'], [class*='match-card'], [class*='match-item']"
                );

                cards.forEach((el) => {
                    const anchor = el.tagName === 'A' ? el : el.querySelector('a') || el.closest('a');
                    if (!anchor || !anchor.href) return;

                    let matchUrl = "";
                    try { matchUrl = new URL(anchor.href, location.href).href; } catch (_) { return; }
                    if (seenUrls.has(matchUrl)) return;
                    seenUrls.add(matchUrl);

                    const cardText = clean(el.innerText || el.textContent);
                    const title = clean(anchor.getAttribute("title") || el.getAttribute("title") || cardText);
                    
                    // Tìm logo trong card
                    const logos = [];
                    el.querySelectorAll("img").forEach((img) => {
                        const src = img.src || img.getAttribute("src") || img.getAttribute("data-src");
                        if (src) logos.push(src);
                    });

                    out.push({
                        url: matchUrl,
                        raw_title: title,
                        card_text: cardText,
                        team_logos: logos,
                        sport_hint: ""
                    });
                });

                return out;
            }"""
        )
        print(f"📌 Đã tìm thấy {len(matches)} trận đấu từ trang chủ.")
    except Exception as exc:
        print(f"❌ Lỗi khi quét trang chủ: {exc}")
    finally:
        await page.close()

    return matches


async def main() -> None:
    print(f"🚀 Khởi động Scanner phiên bản {SCANNER_VERSION}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = await browser.new_context(user_agent=UA, viewport={"width": 1920, "height": 1080})

        matches = await crawl_homepage(context)
        if not matches:
            print("⚠️ Không thu thập được trận đấu nào từ trang chủ. Kết thúc.")
            await browser.close()
            return

        sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
        total = len(matches)
        for idx, match in enumerate(matches, 1):
            match["_scan_index"] = idx
            match["_scan_total"] = total

        tasks = [fetch_stream(context, match, sem) for match in matches]
        results = await asyncio.gather(*tasks)

        await browser.close()

        # Xuất file kết quả debug JSON
        debug_data = {
            "scanner_version": SCANNER_VERSION,
            "target_url": TARGET_URL,
            "scanned_at": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(),
            "total_matches": len(results),
            "matches": results,
        }
        Path(OUTPUT_DEBUG).write_text(json.dumps(debug_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"💾 Đã lưu dữ liệu debug vào {OUTPUT_DEBUG}")

        # Tạo file M3U phát sóng
        generate_m3u_playlists(results)


def generate_m3u_playlists(results: list[dict[str, Any]]) -> None:
    playlist_lines = ["#EXTM3U"]
    pipe_lines = ["#EXTM3U"]
    vlc_lines = ["#EXTM3U"]

    count = 0
    for match in results:
        streams = match.get("streams", [])
        if not streams:
            continue
        
        match_name = match.get("match_name", "Trận đấu")
        sport_group = match.get("sport_group", "Bóng đá")
        logo = match.get("logo", "")
        time_str = match.get("time", "")
        
        for idx, stream in enumerate(streams, 1):
            stream_url = stream["url"]
            referer = stream.get("referer", PLAYER_ORIGIN_FALLBACK + "/")
            ua = stream.get("user_agent", UA)
            
            title_display = f"[{sport_group}] {match_name}"
            if time_str:
                title_display = f"[{time_str}] {title_display}"
            if len(streams) > 1:
                title_display += f" (Link {idx})"

            tvg_id = channel_id_for(match, stream_url, idx)
            
            extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{match_name}" tvg-logo="{logo}" group-title="{sport_group}",{title_display}'
            
            # Playlist chuẩn VLC / IPTV (kèm thông tin http-user-agent và http-referrer)
            playlist_lines.append(extinf)
            playlist_lines.append(f'#EXTVLCOPT:http-user-agent={ua}')
            playlist_lines.append(f'#EXTVLCOPT:http-referrer={referer}')
            playlist_lines.append(stream_url)

            # Playlist dạng Pipe / FFMPEG nếu cần tương thích bộ lọc nâng cao
            pipe_lines.append(extinf)
            pipe_lines.append(stream_url)

            count += 1

    Path(OUTPUT_M3U).write_text("\n".join(playlist_lines), encoding="utf-8")
    Path(OUTPUT_PIPE_M3U).write_text("\n".join(pipe_lines), encoding="utf-8")
    print(f"playlist M3U đã được xuất thành công với {count} kênh phát sóng vào '{OUTPUT_M3U}'.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
