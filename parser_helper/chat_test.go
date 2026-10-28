package main

import (
	"testing"

	"github.com/dotabuff/manta/dota"
	"google.golang.org/protobuf/proto"
)

func TestSayTextRecordedSpeakerChannelAndUnicode(t *testing.T) {
	message := &dota.CUserMessageSayText2{Chat: proto.Bool(true), Messagename: proto.String("DOTA_Chat_All"), Param1: proto.String("\x01Игрок"), Param2: proto.String("\x02你好 gg\n")}
	entry := sayText(message, 120)
	if entry["speaker"] != "Игрок" || entry["text"] != "你好 gg" || entry["channel"] != "All" || entry["tick"] != uint32(120) {
		t.Fatalf("wrong recorded message: %v", entry)
	}
	message.Messagename = proto.String("DOTA_Chat_Team")
	if sayText(message, 121)["channel"] != "Team" {
		t.Fatal("lost team audience")
	}
	message.Chat = proto.Bool(false)
	message.Messagename = proto.String("DOTA_Player_Disconnected")
	if sayText(message, 122) != nil {
		t.Fatal("system notification must not masquerade as player chat")
	}
}

func TestDotaChatUsesResourcePlayerIDAndPreservesUnknownChannel(t *testing.T) {
	message := &dota.CDOTAUserMsg_ChatMessage{SourcePlayerId: proto.Int32(6), ChannelType: proto.Uint32(12), MessageText: proto.String("hello")}
	for _, field := range []string{"m_vecPlayerData.0006.m_iszPlayerName", "m_iszPlayerNames.0006"} {
		entry := dotaChat(message, fake{field: "Six"}, 25)
		if entry["speaker"] != "Six" || entry["channel"] != "Channel 12" {
			t.Fatalf("player resource mapping failed: %v", entry)
		}
	}
	if dotaChat(message, nil, 25)["speaker"] != "Player 6" {
		t.Fatal("missing resource must not guess summary player order")
	}
	message.SourcePlayerId = nil
	if dotaChat(message, nil, 25)["speaker"] != "Unknown player" {
		t.Fatal("missing player id must not become player zero")
	}
	message.MessageText = proto.String(" \x01")
	if dotaChat(message, nil, 25) != nil {
		t.Fatal("empty text should be skipped")
	}
}
