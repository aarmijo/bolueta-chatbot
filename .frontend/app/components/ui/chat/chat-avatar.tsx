import { useChatMessage } from "@llamaindex/chat-ui";
import { UserSearch } from "lucide-react";
import Image from "next/image";

export function ChatMessageAvatar() {
  const { message } = useChatMessage();
  if (message.role === "user") {
    return (
      <div className="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-md border bg-background shadow">
        <UserSearch className="h-4 w-4" />
      </div>
    );
  }

  return (
    <div className="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-md border bg-black text-white shadow">
      <Image
        className="rounded-md"
        src="/bolueta.png"
        alt="Bolueta Logo"
        width={24}
        height={24}
        priority
      />
    </div>
  );
}
