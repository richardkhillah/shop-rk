from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import render, redirect, get_object_or_404
# from django.http import HttpResponse

from store.models import Product, Variation

from .models import Cart, CartItem

# Create your views here.

def _cart_id(request):
    # Use the session id as cart id.
    cart = request.session.session_key
    if not cart:
        cart = request.session.create()
    return cart

def _add_user_to_cart(request, cart=None):
    try:
        if not cart:
            cart = Cart.objects.get(cart_id=_cart_id(request))
        cart.user = request.user
        cart.save()
    except Exception as e:
        print(e)
        cart = None
    return cart

def _update_carts(request, old_cart_id):
    """Update anonymous and users previous cart id to match"""    
    
    users_cart = Cart.objects.filter(user__pk=request.user.id).first()
    anonymous_cart = Cart.objects.filter(cart_id=old_cart_id).first()

    try:
        if users_cart and anonymous_cart:                
            # ideally all of this will be atomic
            # TODO: on update to postgresql use: https://docs.djangoproject.com/en/4.1/ref/models/querysets/#select-for-update
            users_cart.cart_id = _cart_id(request)
            users_cart.save()

            # move anonymous cart items to users previous cart. First check whether
            # the users previous cart contains the unique product, varient combination.
            # If so, increment the already instanciated cart_item quantity by the 
            # New varient quantity.
            # Otherwise, move the product-varient combo to the users cart and add the
            # variation to the existing_product_varients list
            users_cart_items = CartItem.objects.filter(cart=users_cart)

            existing_product_varients = [[item.product.id, *list(item.variations.all())] 
                                            for item in users_cart_items]

            anonymous_cart_items = CartItem.objects.filter(cart=anonymous_cart)
            
            for a_item in anonymous_cart_items:
                varient = [a_item.product.id, *list(a_item.variations.all())]
                if varient in existing_product_varients:
                    # Increment the cart_item quantity and save
                    index = existing_product_varients.index(varient)
                    existing_varient = users_cart_items[index]
                    existing_varient.quantity += a_item.quantity
                    existing_varient.save()
                else:
                    # Move the item over to the cart
                    a_item.cart = users_cart
                    a_item.save()
                    existing_product_varients.append(varient)
            # Declutter the database and get rid of the anonymous cart
            anonymous_cart.delete()

        elif anonymous_cart:
            # This block executes only if 
            # users_cart is None and anonymous_cart is not None
            # 
            # update anonymous cart id to current session and add
            # authenticated user to anonymous cart
            anonymous_cart.cart_id = _cart_id(request)
            _add_user_to_cart(request, anonymous_cart)
            users_cart = anonymous_cart
        elif users_cart:
            # This block executes only if
            # users_cart is not None and anonymous_cart is None
            # 
            # update users previous cart id only
            users_cart.cart_id = _cart_id(request)
            users_cart.save()
    except Exception as e:
        print(e)
        users_cart = None
    finally:
        return users_cart

def _get_post_request_variation(product_id, varients):
    """Parse a dict for variations"""
    product = Product.objects.get(id=product_id)
    product_variations = []
    if isinstance(varients, dict):
        for key, value in varients.items():
            try:
                # Filter out only the relevant information 
                variation = Variation.objects.get(product=product, 
                                                variation_category__iexact=key, 
                                                variation_value__iexact=value)
                # add the product variation
                product_variations.append(variation)
            except:
                # Not a varient
                pass
    return product_variations

def add_item(request, product_id):
    """Increment cart item by one"""
    # Get the product variations from Post request
    product_variation = []
    if request.method == 'POST':
        product_variation = _get_post_request_variation(product_id, request.POST)
    
    # Add the product to the cart
    cart, _ = Cart.objects.get_or_create(cart_id=_cart_id(request))
    product = Product.objects.get(id=product_id)
    cart_items = CartItem.objects.filter(product=product, cart=cart)

    # If the variation already exists in the cart, increment the quantity
    added = False
    for ci in cart_items:
        if product_variation == list(ci.variations.all()):
            ci.quantity += 1
            added = True
            ci.save()
            break
    
    # Otherwise, create a new item
    if not added:
        ci = CartItem.objects.create(product=product, cart=cart, quantity=1)
        ci.variations.add(*product_variation)
        ci.save()
    
    return redirect('cart')

def remove_item(request, product_id, cart_item_id):
    """Decerement cart item by one"""
    product = get_object_or_404(Product, id=product_id)
    cart, _ = Cart.objects.get_or_create(cart_id=_cart_id(request))
    try:
        # Decrement or remove the item varient from the cart
        cart_item = CartItem.objects.get(product=product, cart=cart, id=cart_item_id)
        if cart_item.quantity > 1:
                cart_item.quantity -= 1
                cart_item.save()
        else:
            cart_item.delete()
    except:
        pass
    return redirect('cart')

def remove_cart_item(request, product_id, cart_item_id):
    """Remove all items of the varient from the cart"""
    product = get_object_or_404(Product, id=product_id)
    cart = Cart.objects.get(cart_id=_cart_id(request))
    try:
        cart_item = CartItem.objects.filter(product=product, cart=cart, id=cart_item_id)
        cart_item.delete()
    except:
        pass
    return redirect('cart')


def cart(request, total=0, quantity=0, cart_items=None):
    try:
        cart = Cart.objects.get(cart_id=_cart_id(request))
        cart_items = CartItem.objects.filter(cart=cart, is_active=True)
        for cart_item in cart_items:
            total += (cart_item.product.price * cart_item.quantity)
            quantity += cart_item.quantity
        tax = 0.095 * total
        grand_total = total + tax
    except ObjectDoesNotExist:
        #TODO: Fix this Make handling better
        tax=0
        grand_total=0

    context = {
        'total': total,
        'tax': tax,
        'grand_total': grand_total,
        'quantity': quantity,
        'cart_items': cart_items,
    }

    return render(request, 'cart.html', context=context)

@login_required(login_url='login')
def checkout(request, total=0, quantity=0, cart_items=None):
    try:
        cart = Cart.objects.get(cart_id=_cart_id(request))
        cart_items = CartItem.objects.filter(cart=cart, is_active=True)
        for cart_item in cart_items:
            total += (cart_item.product.price * cart_item.quantity)
            quantity += cart_item.quantity
        tax = 0.095 * total
        grand_total = total + tax
    except ObjectDoesNotExist:
        #TODO: Fix this Make handling better
        tax=0
        grand_total=0

    context = {
        'total': total,
        'tax': tax,
        'grand_total': grand_total,
        'quantity': quantity,
        'cart_items': cart_items,
    }

    return render(request, 'checkout.html', context=context)