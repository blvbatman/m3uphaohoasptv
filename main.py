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
            
            # Playlist chuẩn (Android TV / Mặc định) kèm tag VLCopt
            playlist_lines.append(extinf)
            playlist_lines.append(f'#EXTVLCOPT:http-user-agent={ua}')
            playlist_lines.append(f'#EXTVLCOPT:http-referrer={referer}')
            playlist_lines.append(stream_url)

            # Playlist dạng Pipe / Kodi (nối trực tiếp User-Agent và Referer vào URL)
            pipe_url = f"{stream_url}|User-Agent={quote(ua)}&Referer={quote(referer)}"
            pipe_lines.append(extinf)
            pipe_lines.append(pipe_url)

            # Playlist chuẩn VLC riêng biệt
            vlc_lines.append(extinf)
            vlc_lines.append(f'#EXTVLCOPT:http-user-agent={ua}')
            vlc_lines.append(f'#EXTVLCOPT:http-referrer={referer}')
            vlc_lines.append(stream_url)

            count += 1

    Path(OUTPUT_M3U).write_text("\n".join(playlist_lines), encoding="utf-8")
    Path(OUTPUT_PIPE_M3U).write_text("\n".join(pipe_lines), encoding="utf-8")
    Path(OUTPUT_VLC_M3U).write_text("\n".join(vlc_lines), encoding="utf-8")
    print(f"📁 Đã xuất các file playlist M3U thành công ({count} luồng).")
