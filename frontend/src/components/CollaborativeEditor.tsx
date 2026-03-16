import { useEffect, useRef, useState } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Collaboration from '@tiptap/extension-collaboration';
import CollaborationCursor from '@tiptap/extension-collaboration-cursor';
import * as Y from 'yjs';
import { WebsocketProvider } from 'y-websocket';

interface Props {
	blogId: string;
	token: string;
	userEmail: string;
	username?: string;
	onContentChange: (html: string) => void;
	initialContent?: string;
}

const USER_COLORS = ['#f59e0b', '#10b981', '#3b82f6', '#ec4899', '#8b5cf6', '#ef4444'];
const randomColor = () => USER_COLORS[Math.floor(Math.random() * USER_COLORS.length)];

type CollabSession = {
	ydoc: Y.Doc;
	provider: WebsocketProvider;
};

function CollaborativeEditorInner({
	session,
	userEmail,
	username,
	onContentChange,
	initialContent,
	wsStatus,
	isSynced,
}: {
	session: CollabSession;
	userEmail: string;
	username?: string;
	onContentChange: (html: string) => void;
	initialContent?: string;
	wsStatus: 'connected' | 'disconnected' | 'connecting';
	isSynced: boolean;
}) {
	const colorRef = useRef(randomColor());
	const seededRef = useRef(false);
	const { ydoc, provider } = session;

	const editor = useEditor({
		extensions: [
			StarterKit.configure({ history: false }),
			Collaboration.configure({ document: ydoc }),
			CollaborationCursor.configure({
				provider,
				user: { name: username || userEmail, color: colorRef.current },
			}),
		],
		onUpdate({ editor }) {
			onContentChange(editor.getHTML());
		},
	});

	// Only seed content once when sync completes
	useEffect(() => {
		if (!editor || !initialContent || seededRef.current) return;

		const seedIfEmpty = () => {
			// Check if Yjs document already has content
			const ytext = ydoc.getText('shared');
			const hasYjsContent = ytext.length > 0;
			
			if (!hasYjsContent) {
				editor.commands.setContent(initialContent, false);
				seededRef.current = true;
			} else {
				// Mark as seeded even if there's existing content
				seededRef.current = true;
			}
		};

		// Only seed once when sync is confirmed
		if (isSynced) {
			seedIfEmpty();
		}
	}, [editor, initialContent, isSynced, ydoc]);

	return (
		<div className="collab-editor">
			<div className="collab-editor-status">
				WS: {wsStatus} | Sync: {isSynced ? 'ready' : 'pending'}
			</div>
			<EditorContent editor={editor} />
		</div>
	);
}

export default function CollaborativeEditor({
	blogId,
	token,
	userEmail,
	username,
	onContentChange,
	initialContent,
}: Props) {
	const [wsStatus, setWsStatus] = useState<'connected' | 'disconnected' | 'connecting'>('connecting');
	const [isSynced, setIsSynced] = useState(false);
	const [session, setSession] = useState<CollabSession | null>(null);

	useEffect(() => {
		const ydoc = new Y.Doc();
		const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
		const wsServer = (
			import.meta.env.VITE_WS_BASE_URL || `${proto}://${window.location.host}/ws/collab`
		).trim();
		const provider = new WebsocketProvider(wsServer, blogId, ydoc, {
			params: { token },
			connect: true,
		});

		setSession({ ydoc, provider });
		setWsStatus(provider.wsconnected ? 'connected' : 'connecting');
		setIsSynced(Boolean(provider.synced));

		const handleStatus = (event: { status: 'connected' | 'disconnected' | 'connecting' }) => {
			setWsStatus(event.status);
		};

		const handleSyncState = (synced: boolean) => {
			setIsSynced(synced);
		};

		const handleVisibilityChange = () => {
			if (document.hidden) return;
			// Tab became visible - force reconnect and resync
			provider.disconnect();
			setTimeout(() => provider.connect(), 100);
		};

		provider.on('status', handleStatus);
		provider.on('sync', handleSyncState);
		document.addEventListener('visibilitychange', handleVisibilityChange);

		return () => {
			provider.off('status', handleStatus);
			provider.off('sync', handleSyncState);
			document.removeEventListener('visibilitychange', handleVisibilityChange);
			provider.destroy();
			ydoc.destroy();
			setSession(null);
		};
	}, [blogId, token]);

	if (!session) {
		return (
			<div className="collab-editor">
				<div className="collab-editor-status">WS: connecting | Sync: pending</div>
			</div>
		);
	}

	return (
		<CollaborativeEditorInner
			session={session}
			userEmail={userEmail}
			username={username}
			onContentChange={onContentChange}
			initialContent={initialContent}
			wsStatus={wsStatus}
			isSynced={isSynced}
		/>
	);
}
