from backend.cursor_lock import CursorLock


def test_contact_locks_cursor_and_mouse_takes_priority_until_lift():
    desktop=(-1920,0,1920,1080)
    bounds=[desktop]
    calls=[]
    def clip(rect):
        bounds[0]=rect;calls.append(rect)
    guard=CursorLock(lambda:bounds[0],clip,(200,300))
    guard.touch(True)
    assert bounds[0]==(200,300,201,301)
    guard.touch(True)
    assert len(calls)==1
    guard.external_mouse()
    assert bounds[0]==desktop
    guard.touch(True)
    assert bounds[0]==desktop
    guard.touch(False)
    guard.anchor=(500,600)
    guard.touch(True)
    assert bounds[0]==(500,600,501,601)
    guard.release()  # Focus loss / shutdown.
    assert bounds[0]==desktop


def test_release_preserves_another_app_clip_and_failure_does_not_claim_lock():
    bounds=[(0,0,1920,1080)]
    def clip(rect):bounds[0]=rect
    guard=CursorLock(lambda:bounds[0],clip,(80,90))
    guard.touch(True)
    bounds[0]=(0,0,100,100)
    guard.release()
    assert bounds[0]==(0,0,100,100)
    def failing_clip(rect):raise OSError('denied')
    guard=CursorLock(lambda:bounds[0],failing_clip,(20,30))
    try:guard.touch(True)
    except OSError:pass
    else:raise AssertionError('Expected native error')
    assert guard.locked is None
