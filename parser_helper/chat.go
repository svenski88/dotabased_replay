package main

import (
	"fmt"
	"strings"
	"unicode"

	"github.com/dotabuff/manta/dota"
)

// Strip Source text color/control bytes while preserving international text.
func chatText(value string) string {
	return strings.Map(func(r rune) rune {
		if unicode.IsControl(r) {
			return -1
		}
		return r
	}, value)
}

func sayText(message *dota.CUserMessageSayText2, tick uint32) map[string]interface{} {
	if !message.GetChat() && !strings.Contains(message.GetMessagename(), "DOTA_Chat_") {
		return nil
	}
	text := chatText(message.GetParam2())
	if strings.TrimSpace(text) == "" {
		return nil
	}
	channel := "Chat"
	token := strings.ToLower(message.GetMessagename())
	if strings.Contains(token, "all") {
		channel = "All"
	} else if strings.Contains(token, "team") {
		channel = "Team"
	}
	return map[string]interface{}{"tick": tick, "speaker": chatText(message.GetParam1()), "text": text, "channel": channel}
}

func dotaChat(message *dota.CDOTAUserMsg_ChatMessage, players getter, tick uint32) map[string]interface{} {
	text := chatText(message.GetMessageText())
	if strings.TrimSpace(text) == "" {
		return nil
	}
	speaker := "Unknown player"
	if message.SourcePlayerId != nil && message.GetSourcePlayerId() >= 0 {
		id := message.GetSourcePlayerId()
		speaker = fmt.Sprintf("Player %d", id)
		if players != nil {
			for _, key := range []string{fmt.Sprintf("m_vecPlayerData.%04d.m_iszPlayerName", id), fmt.Sprintf("m_iszPlayerNames.%04d", id)} {
				if name, ok := players.Get(key).(string); ok && name != "" {
					speaker = chatText(name)
					break
				}
			}
		}
	}
	channel := "Chat"
	if message.ChannelType != nil {
		// Preserve the recorded enum; do not guess its audience across builds.
		channel = fmt.Sprintf("Channel %d", message.GetChannelType())
	}
	return map[string]interface{}{"tick": tick, "speaker": speaker, "text": text, "channel": channel}
}
