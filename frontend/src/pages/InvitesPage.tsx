import { useEffect, useState } from 'react';
import { invitesApi } from '../api';
import { getApiErrorMessage, notifyError, notifySuccess } from '../utils/toast';
import { FiCheck, FiX, FiMinus, FiClock, FiMail } from 'react-icons/fi';
import './Invites.css';

interface Invite {
  id: string;
  sender_id: string;
  sender_username: string | null;
  sender_email: string;
  recipient_id: string;
  recipient_username: string | null;
  recipient_email: string;
  blog_id: string;
  blog_title: string;
  status: string;
  created_at: string;
  updated_at: string;
}

type Tab = 'received' | 'sent';

export default function InvitesPage() {
  const [tab, setTab] = useState<Tab>('received');
  const [received, setReceived] = useState<Invite[]>([]);
  const [sent, setSent] = useState<Invite[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<string | null>(null);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [recRes, sentRes] = await Promise.all([
        invitesApi.received(),
        invitesApi.sent(),
      ]);
      setReceived(Array.isArray(recRes.data) ? recRes.data : []);
      setSent(Array.isArray(sentRes.data) ? sentRes.data : []);
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'Failed to load invites'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const handleAccept = async (id: string) => {
    setActionId(id);
    try {
      await invitesApi.accept(id);
      notifySuccess('Invite accepted! You can now collaborate on this blog.');
      await loadAll();
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'Failed to accept invite'));
    } finally {
      setActionId(null);
    }
  };

  const handleReject = async (id: string) => {
    setActionId(id);
    try {
      await invitesApi.reject(id);
      notifySuccess('Invite rejected.');
      await loadAll();
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'Failed to reject invite'));
    } finally {
      setActionId(null);
    }
  };

  const handleCancel = async (id: string) => {
    if (!window.confirm('Cancel this invite?')) return;
    setActionId(id);
    try {
      await invitesApi.cancel(id);
      notifySuccess('Invite cancelled.');
      await loadAll();
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'Failed to cancel invite'));
    } finally {
      setActionId(null);
    }
  };

  const handleRemoveCollaborator = async (id: string) => {
    if (!window.confirm('Remove this collaborator? They will lose access to collaborate on this blog.')) return;
    setActionId(id);
    try {
      await invitesApi.removeCollaborator(id);
      notifySuccess('Collaborator removed.');
      await loadAll();
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'Failed to remove collaborator'));
    } finally {
      setActionId(null);
    }
  };

  const statusBadge = (status: string) => (
    <span className={`invite-status-badge invite-status-${status}`}>{status}</span>
  );

  const formatDate = (d: string) => new Date(d).toLocaleDateString();

  const renderReceivedInvite = (inv: Invite) => (
    <div key={inv.id} className="invite-card">
      <div className="invite-card-body">
        <div className="invite-info">
          <FiMail className="invite-icon" />
          <div>
            <p className="invite-title">
              <strong>{inv.sender_username ? `@${inv.sender_username}` : inv.sender_email}</strong>
              {' '}invited you to collaborate on{' '}
              <strong>"{inv.blog_title}"</strong>
            </p>
            <p className="invite-date">
              <FiClock /> {formatDate(inv.created_at)} &middot; {statusBadge(inv.status)}
            </p>
          </div>
        </div>
        {inv.status === 'pending' && (
          <div className="invite-actions">
            <button
              className="btn btn-primary btn-sm"
              onClick={() => handleAccept(inv.id)}
              disabled={actionId === inv.id}
            >
              <FiCheck /> Accept
            </button>
            <button
              className="btn btn-danger btn-sm"
              onClick={() => handleReject(inv.id)}
              disabled={actionId === inv.id}
            >
              <FiX /> Reject
            </button>
          </div>
        )}
      </div>
    </div>
  );

  const renderSentInvite = (inv: Invite) => (
    <div key={inv.id} className="invite-card">
      <div className="invite-card-body">
        <div className="invite-info">
          <FiMail className="invite-icon" />
          <div>
            <p className="invite-title">
              You invited{' '}
              <strong>{inv.recipient_username ? `@${inv.recipient_username}` : inv.recipient_email}</strong>
              {' '}to collaborate on{' '}
              <strong>"{inv.blog_title}"</strong>
            </p>
            <p className="invite-date">
              <FiClock /> {formatDate(inv.created_at)} &middot; {statusBadge(inv.status)}
            </p>
          </div>
        </div>
        <div className="invite-actions">
          {inv.status === 'pending' && (
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => handleCancel(inv.id)}
              disabled={actionId === inv.id}
            >
              <FiMinus /> Cancel
            </button>
          )}
          {inv.status === 'accepted' && (
            <button
              className="btn btn-danger btn-sm"
              onClick={() => handleRemoveCollaborator(inv.id)}
              disabled={actionId === inv.id}
            >
              <FiX /> Remove Collaborator
            </button>
          )}
        </div>
      </div>
    </div>
  );

  if (loading) return <div className="loading">Loading invites...</div>;

  const pendingCount = received.filter((i) => i.status === 'pending').length;
  const unreadSentCount = sent.filter((i) => ['accepted','rejected'].includes(i.status)).length;

  return (
    <div className="invites-page">
      <div className="page-header">
        <h1>Collaboration Invites</h1>
      </div>

      <div className="invites-tabs">
        <button
          className={`invite-tab ${tab === 'received' ? 'active' : ''}`}
          onClick={() => setTab('received')}
        >
          Received
          {pendingCount > 0 && <span className="tab-badge">{pendingCount}</span>}
        </button>
        <button
          className={`invite-tab ${tab === 'sent' ? 'active' : ''}`}
          onClick={() => setTab('sent')}
        >
          Sent
          {unreadSentCount > 0 && <span className="tab-badge">{unreadSentCount}</span>}
        </button>
      </div>

      <div className="invites-list">
        {tab === 'received' ? (
          received.length === 0 ? (
            <div className="empty-state"><p>No invites received yet.</p></div>
          ) : (
            received.map(renderReceivedInvite)
          )
        ) : (
          sent.length === 0 ? (
            <div className="empty-state"><p>No invites sent yet.</p></div>
          ) : (
            sent.map(renderSentInvite)
          )
        )}
      </div>
    </div>
  );
}
