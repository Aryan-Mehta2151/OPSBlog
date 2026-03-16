import { useEffect, useState } from 'react';
import { invitesApi, blogsApi } from '../api';
import { useAuth } from '../context/AuthContext';
import { getApiErrorMessage, notifyError, notifySuccess } from '../utils/toast';
import { FiSend } from 'react-icons/fi';
import './Invites.css';

interface OrgUser {
  id: string;
  username: string | null;
  email: string;
}

interface Blog {
  id: string;
  title: string;
  status: string;
  author_id: string;
}

export default function SendInvitePage() {
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [blogs, setBlogs] = useState<Blog[]>([]);
  const { user } = useAuth();
  const [selectedUserId, setSelectedUserId] = useState('');
  const [selectedBlogId, setSelectedBlogId] = useState('');
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadData = async () => {
      try {
        const [usersRes, blogsRes] = await Promise.all([
          invitesApi.orgUsers(),
          blogsApi.list(),
        ]);
        const orgUsers = Array.isArray(usersRes.data) ? usersRes.data : [];
        const allBlogs: Blog[] = Array.isArray(blogsRes.data) ? blogsRes.data : [];
        setUsers(orgUsers);
        // Only show blogs the current user authored (they must be owner to send invites)
        setBlogs(allBlogs.filter((b) => b.author_id === user?.id));
      } catch (err: any) {
        notifyError(getApiErrorMessage(err, 'Failed to load data'));
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [user?.id]);

  const safeUsers = Array.isArray(users) ? users : [];

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUserId || !selectedBlogId) {
      notifyError('Please select a user and a blog');
      return;
    }
    const selectedUser = safeUsers.find((u) => u.id === selectedUserId);
    if (!selectedUser) return;

    setSending(true);
    try {
      await invitesApi.send({
        recipient_id: selectedUser.id,
        recipient_username: selectedUser.username || selectedUser.email,
        blog_id: selectedBlogId,
      });
      notifySuccess('Invite sent successfully!');
      setSelectedUserId('');
      setSelectedBlogId('');
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'Failed to send invite'));
    } finally {
      setSending(false);
    }
  };

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div className="invites-page">
      <div className="page-header">
        <h1>Send Collaboration Invite</h1>
        <p className="page-subtitle">
          Invite a teammate to collaborate on one of your blogs in real time.
        </p>
      </div>

      <form className="invite-form" onSubmit={handleSend}>
        {/* User dropdown */}
        <div className="invite-form-group">
          <label>Select User</label>
          {safeUsers.length === 0 ? (
            <p className="invite-form-hint">No other users found in your organization.</p>
          ) : (
            <select
              className="invite-blog-select"
              value={selectedUserId}
              onChange={(e) => setSelectedUserId(e.target.value)}
              required
            >
              <option value="">-- Choose a user --</option>
              {safeUsers.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username ? `@${u.username}` : u.email}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Blog selector */}
        <div className="invite-form-group">
          <label>Select Your Blog</label>
          {blogs.length === 0 ? (
            <p className="invite-form-hint">You have no blogs yet. Create a blog first.</p>
          ) : (
            <select
              className="invite-blog-select"
              value={selectedBlogId}
              onChange={(e) => setSelectedBlogId(e.target.value)}
              required
            >
              <option value="">-- Choose a blog --</option>
              {blogs.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.title} ({b.status})
                </option>
              ))}
            </select>
          )}
        </div>

        <button
          type="submit"
          className="btn btn-primary"
          disabled={sending || !selectedUserId || !selectedBlogId}
        >
          <FiSend /> {sending ? 'Sending...' : 'Send Invite'}
        </button>
      </form>
    </div>
  );
}
